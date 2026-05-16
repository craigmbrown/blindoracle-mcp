// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/**
 * @title BlindOracle Ideal State Contract
 * @notice Escrow contract where payment releases only when verification criteria pass.
 *         Requester defines expected outcome criteria before execution.
 *         Multi-party verification (3-of-5 verifiers) confirms criteria met.
 *
 * Flow:
 *   1. Requester creates task with criteria + funds escrow
 *   2. Agent executes task off-chain
 *   3. Verifiers submit verification results
 *   4. If consensus reached (3/5 verified), agent gets paid
 *   5. If verification fails, requester gets refund (minus gas)
 *   6. Timeout: requester can reclaim after deadline
 *
 * @dev Uses pull-payment pattern. No reentrancy risk via checks-effects-interactions.
 *
 * Copyright (c) 2025-2026 Craig M. Brown. All rights reserved.
 */
contract IdealStateContract {
    // ============================================================
    // ENUMS & STRUCTS
    // ============================================================

    enum TaskStatus { Created, Funded, Executing, Verifying, Completed, Failed, Expired }

    struct VerificationCriteria {
        uint32  maxDurationSecs;     // max execution time
        uint256 maxCostWei;          // max cost in wei
        string  requiredKeywords;    // comma-separated keywords in output
        uint16  minConfidence;       // 0-10000 (100.00%)
        bool    requireProofChain;   // must have Nostr proof attestation
        uint16  minOutputLength;     // minimum output chars
    }

    struct Task {
        bytes32      taskId;
        address      requester;
        address      agent;
        string       description;
        uint256      escrowAmount;
        TaskStatus   status;
        uint64       createdAt;
        uint64       deadline;
        uint8        verificationsRequired;  // e.g. 3
        uint8        verificationsReceived;
        uint8        verificationsApproved;
        bytes32      resultHash;             // hash of agent output
    }

    struct Verification {
        address verifier;
        bool    approved;
        uint16  confidence;
        bytes32 receiptHash;
        uint64  submittedAt;
    }

    // ============================================================
    // STATE
    // ============================================================

    address public owner;
    address public agentRegistry;  // AgentRegistry contract address

    uint256 public taskCount;
    uint256 public totalEscrowedWei;
    uint256 public totalReleasedWei;
    uint256 public totalRefundedWei;

    mapping(bytes32 => Task) public tasks;
    mapping(bytes32 => VerificationCriteria) public criteria;
    mapping(bytes32 => Verification[]) public verifications;
    mapping(bytes32 => mapping(address => bool)) public hasVerified;
    mapping(address => bool) public authorizedVerifiers;

    bytes32[] public taskIds;

    // ============================================================
    // EVENTS
    // ============================================================

    event TaskCreated(bytes32 indexed taskId, address requester, uint256 escrow, uint64 deadline);
    event TaskFunded(bytes32 indexed taskId, uint256 amount);
    event TaskAssigned(bytes32 indexed taskId, address agent);
    event ResultSubmitted(bytes32 indexed taskId, bytes32 resultHash);
    event VerificationSubmitted(bytes32 indexed taskId, address verifier, bool approved, uint16 confidence);
    event TaskCompleted(bytes32 indexed taskId, address agent, uint256 payout);
    event TaskFailed(bytes32 indexed taskId, address requester, uint256 refund);
    event TaskExpired(bytes32 indexed taskId, address requester, uint256 refund);
    event VerifierAdded(address verifier);
    event VerifierRemoved(address verifier);

    // ============================================================
    // MODIFIERS
    // ============================================================

    modifier onlyOwner() {
        require(msg.sender == owner, "IdealState: not owner");
        _;
    }

    modifier onlyVerifier() {
        require(authorizedVerifiers[msg.sender], "IdealState: not verifier");
        _;
    }

    // ============================================================
    // CONSTRUCTOR
    // ============================================================

    constructor(address _agentRegistry) {
        owner = msg.sender;
        agentRegistry = _agentRegistry;
    }

    // ============================================================
    // TASK LIFECYCLE
    // ============================================================

    /**
     * @notice Create a task with verification criteria and fund escrow.
     * @param description       Human-readable task description
     * @param agent             Address of the assigned agent
     * @param deadlineSeconds   Seconds from now until task expires
     * @param verifRequired     Number of verifications needed (e.g. 3)
     * @param maxDurationSecs   Max execution duration
     * @param maxCostWei        Max cost in wei
     * @param requiredKeywords  Comma-separated keywords
     * @param minConfidence     Minimum confidence (0-10000)
     * @param requireProof      Require proof chain
     * @param minOutputLen      Minimum output length
     */
    function createTask(
        string calldata description,
        address agent,
        uint32  deadlineSeconds,
        uint8   verifRequired,
        uint32  maxDurationSecs,
        uint256 maxCostWei,
        string calldata requiredKeywords,
        uint16  minConfidence,
        bool    requireProof,
        uint16  minOutputLen
    ) external payable returns (bytes32) {
        require(msg.value > 0, "IdealState: must fund escrow");
        require(verifRequired >= 1 && verifRequired <= 10, "IdealState: bad verif count");

        bytes32 taskId = keccak256(
            abi.encodePacked(msg.sender, agent, block.timestamp, taskCount)
        );

        tasks[taskId] = Task({
            taskId: taskId,
            requester: msg.sender,
            agent: agent,
            description: description,
            escrowAmount: msg.value,
            status: TaskStatus.Funded,
            createdAt: uint64(block.timestamp),
            deadline: uint64(block.timestamp + deadlineSeconds),
            verificationsRequired: verifRequired,
            verificationsReceived: 0,
            verificationsApproved: 0,
            resultHash: bytes32(0)
        });

        criteria[taskId] = VerificationCriteria({
            maxDurationSecs: maxDurationSecs,
            maxCostWei: maxCostWei,
            requiredKeywords: requiredKeywords,
            minConfidence: minConfidence,
            requireProofChain: requireProof,
            minOutputLength: minOutputLen
        });

        taskIds.push(taskId);
        taskCount++;
        totalEscrowedWei += msg.value;

        emit TaskCreated(taskId, msg.sender, msg.value, tasks[taskId].deadline);
        emit TaskAssigned(taskId, agent);

        return taskId;
    }

    /**
     * @notice Agent submits result hash after off-chain execution.
     */
    function submitResult(bytes32 taskId, bytes32 resultHash) external {
        Task storage t = tasks[taskId];
        require(t.taskId != bytes32(0), "IdealState: task not found");
        require(msg.sender == t.agent, "IdealState: not assigned agent");
        require(t.status == TaskStatus.Funded, "IdealState: wrong status");
        require(block.timestamp <= t.deadline, "IdealState: expired");

        t.resultHash = resultHash;
        t.status = TaskStatus.Verifying;

        emit ResultSubmitted(taskId, resultHash);
    }

    /**
     * @notice Verifier submits verification result.
     */
    function submitVerification(
        bytes32 taskId,
        bool    approved,
        uint16  confidence,
        bytes32 receiptHash
    ) external onlyVerifier {
        Task storage t = tasks[taskId];
        require(t.status == TaskStatus.Verifying, "IdealState: not verifying");
        require(!hasVerified[taskId][msg.sender], "IdealState: already verified");
        require(block.timestamp <= t.deadline, "IdealState: expired");

        hasVerified[taskId][msg.sender] = true;
        verifications[taskId].push(Verification({
            verifier: msg.sender,
            approved: approved,
            confidence: confidence,
            receiptHash: receiptHash,
            submittedAt: uint64(block.timestamp)
        }));

        t.verificationsReceived++;
        if (approved) {
            t.verificationsApproved++;
        }

        emit VerificationSubmitted(taskId, msg.sender, approved, confidence);

        // Check if consensus reached
        if (t.verificationsApproved >= t.verificationsRequired) {
            _completeTask(taskId);
        } else if (
            t.verificationsReceived - t.verificationsApproved >
            (10 - t.verificationsRequired)  // impossible to reach threshold
        ) {
            _failTask(taskId);
        }
    }

    /**
     * @notice Reclaim escrow after deadline passes without completion.
     */
    function reclaimExpired(bytes32 taskId) external {
        Task storage t = tasks[taskId];
        require(t.taskId != bytes32(0), "IdealState: task not found");
        require(msg.sender == t.requester, "IdealState: not requester");
        require(block.timestamp > t.deadline, "IdealState: not expired");
        require(
            t.status != TaskStatus.Completed && t.status != TaskStatus.Expired,
            "IdealState: already settled"
        );

        t.status = TaskStatus.Expired;
        uint256 refund = t.escrowAmount;
        totalRefundedWei += refund;

        (bool success, ) = payable(t.requester).call{value: refund}("");
        require(success, "IdealState: refund failed");

        emit TaskExpired(taskId, t.requester, refund);
    }

    // ============================================================
    // INTERNAL
    // ============================================================

    function _completeTask(bytes32 taskId) internal {
        Task storage t = tasks[taskId];
        t.status = TaskStatus.Completed;

        uint256 payout = t.escrowAmount;
        totalReleasedWei += payout;

        (bool success, ) = payable(t.agent).call{value: payout}("");
        require(success, "IdealState: payout failed");

        emit TaskCompleted(taskId, t.agent, payout);
    }

    function _failTask(bytes32 taskId) internal {
        Task storage t = tasks[taskId];
        t.status = TaskStatus.Failed;

        uint256 refund = t.escrowAmount;
        totalRefundedWei += refund;

        (bool success, ) = payable(t.requester).call{value: refund}("");
        require(success, "IdealState: refund failed");

        emit TaskFailed(taskId, t.requester, refund);
    }

    // ============================================================
    // ADMIN
    // ============================================================

    function addVerifier(address verifier) external onlyOwner {
        authorizedVerifiers[verifier] = true;
        emit VerifierAdded(verifier);
    }

    function removeVerifier(address verifier) external onlyOwner {
        authorizedVerifiers[verifier] = false;
        emit VerifierRemoved(verifier);
    }

    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "IdealState: zero address");
        owner = newOwner;
    }

    // ============================================================
    // VIEWS
    // ============================================================

    function getTask(bytes32 taskId) external view returns (Task memory) {
        return tasks[taskId];
    }

    function getCriteria(bytes32 taskId) external view returns (VerificationCriteria memory) {
        return criteria[taskId];
    }

    function getVerifications(bytes32 taskId) external view returns (Verification[] memory) {
        return verifications[taskId];
    }

    function getTaskCount() external view returns (uint256) {
        return taskCount;
    }
}
