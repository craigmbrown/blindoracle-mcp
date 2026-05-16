// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/**
 * @title BlindOracle Agent Registry
 * @notice On-chain registry for agent reputation, capabilities, and verification receipts.
 *         CRE cron job batch-updates reputation scores weekly.
 *
 * @dev Deployed on Base (L2) for low gas costs.
 *      Owner = BlindOracle multisig. Updater = CRE automation contract.
 *
 * Copyright (c) 2025-2026 Craig M. Brown. All rights reserved.
 */
contract AgentRegistry {
    // ============================================================
    // STRUCTS
    // ============================================================

    struct Agent {
        string name;            // e.g. "budget-tracker-agent"
        string team;            // e.g. "finance"
        uint16 reputationScore; // 0-10000 (100.00 scaled by 100)
        uint8  level;           // 1-10
        string badge;           // "platinum", "gold", "silver", "bronze"
        uint32 totalRuns;       // lifetime run count
        uint32 successfulRuns;  // lifetime successes
        uint16 slaPct;          // SLA compliance 0-10000 (100.00%)
        uint64 registeredAt;    // block.timestamp of registration
        uint64 lastUpdatedAt;   // block.timestamp of last reputation update
        bool   active;          // can accept tasks
    }

    struct VerificationReceipt {
        bytes32 receiptHash;    // SHA-256 of verification result
        string  agentName;      // agent that was verified
        bool    verified;       // pass/fail
        uint16  confidence;     // 0-10000 (100.00%)
        uint64  verifiedAt;     // block.timestamp
    }

    // ============================================================
    // STATE
    // ============================================================

    address public owner;
    address public updater;  // CRE automation address

    mapping(string => Agent) public agents;
    string[] public agentNames;

    VerificationReceipt[] public receipts;

    uint256 public totalAgents;
    uint256 public totalReceipts;
    uint64  public lastBatchUpdate;

    // ============================================================
    // EVENTS
    // ============================================================

    event AgentRegistered(string indexed name, string team, uint64 timestamp);
    event AgentDeactivated(string indexed name, uint64 timestamp);
    event ReputationUpdated(
        string indexed name,
        uint16 oldScore,
        uint16 newScore,
        string badge,
        uint64 timestamp
    );
    event VerificationRecorded(
        bytes32 indexed receiptHash,
        string agentName,
        bool verified,
        uint16 confidence,
        uint64 timestamp
    );
    event BatchUpdateCompleted(uint256 agentsUpdated, uint64 timestamp);
    event UpdaterChanged(address oldUpdater, address newUpdater);

    // ============================================================
    // MODIFIERS
    // ============================================================

    modifier onlyOwner() {
        require(msg.sender == owner, "AgentRegistry: caller is not owner");
        _;
    }

    modifier onlyUpdater() {
        require(
            msg.sender == updater || msg.sender == owner,
            "AgentRegistry: caller is not updater"
        );
        _;
    }

    // ============================================================
    // CONSTRUCTOR
    // ============================================================

    constructor(address _updater) {
        owner = msg.sender;
        updater = _updater;
    }

    // ============================================================
    // REGISTRATION
    // ============================================================

    /**
     * @notice Register a new agent in the on-chain registry.
     * @param name  Unique agent identifier (e.g. "budget-tracker-agent")
     * @param team  Team name (e.g. "finance", "intercabal")
     */
    function registerAgent(string calldata name, string calldata team)
        external
        onlyUpdater
    {
        require(agents[name].registeredAt == 0, "AgentRegistry: already registered");

        agents[name] = Agent({
            name: name,
            team: team,
            reputationScore: 5000, // start at 50.00
            level: 1,
            badge: "bronze",
            totalRuns: 0,
            successfulRuns: 0,
            slaPct: 0,
            registeredAt: uint64(block.timestamp),
            lastUpdatedAt: uint64(block.timestamp),
            active: true
        });
        agentNames.push(name);
        totalAgents++;

        emit AgentRegistered(name, team, uint64(block.timestamp));
    }

    /**
     * @notice Batch-register multiple agents (gas efficient for initial setup).
     */
    function batchRegisterAgents(
        string[] calldata names,
        string[] calldata teams
    ) external onlyUpdater {
        require(names.length == teams.length, "AgentRegistry: length mismatch");
        for (uint256 i = 0; i < names.length; i++) {
            if (agents[names[i]].registeredAt == 0) {
                agents[names[i]] = Agent({
                    name: names[i],
                    team: teams[i],
                    reputationScore: 5000,
                    level: 1,
                    badge: "bronze",
                    totalRuns: 0,
                    successfulRuns: 0,
                    slaPct: 0,
                    registeredAt: uint64(block.timestamp),
                    lastUpdatedAt: uint64(block.timestamp),
                    active: true
                });
                agentNames.push(names[i]);
                totalAgents++;
                emit AgentRegistered(names[i], teams[i], uint64(block.timestamp));
            }
        }
    }

    function deactivateAgent(string calldata name) external onlyOwner {
        require(agents[name].registeredAt > 0, "AgentRegistry: not registered");
        agents[name].active = false;
        emit AgentDeactivated(name, uint64(block.timestamp));
    }

    // ============================================================
    // REPUTATION UPDATES (CRE batch job)
    // ============================================================

    /**
     * @notice Update reputation for a single agent.
     * @param name           Agent identifier
     * @param score          Reputation score (0-10000, e.g. 9820 = 98.20)
     * @param level          Agent level (1-10)
     * @param badge          Badge string ("platinum"/"gold"/"silver"/"bronze")
     * @param _totalRuns     Lifetime total runs
     * @param _successfulRuns Lifetime successful runs
     * @param _slaPct        SLA compliance (0-10000)
     */
    function updateReputation(
        string calldata name,
        uint16 score,
        uint8  level,
        string calldata badge,
        uint32 _totalRuns,
        uint32 _successfulRuns,
        uint16 _slaPct
    ) external onlyUpdater {
        require(agents[name].registeredAt > 0, "AgentRegistry: not registered");

        uint16 oldScore = agents[name].reputationScore;
        agents[name].reputationScore = score;
        agents[name].level = level;
        agents[name].badge = badge;
        agents[name].totalRuns = _totalRuns;
        agents[name].successfulRuns = _successfulRuns;
        agents[name].slaPct = _slaPct;
        agents[name].lastUpdatedAt = uint64(block.timestamp);

        emit ReputationUpdated(name, oldScore, score, badge, uint64(block.timestamp));
    }

    /**
     * @notice Batch-update reputation for multiple agents (weekly CRE cron).
     *         Packed args to minimize calldata/gas.
     */
    function batchUpdateReputation(
        string[]  calldata names,
        uint16[]  calldata scores,
        uint8[]   calldata levels,
        string[]  calldata badges,
        uint32[]  calldata runs,
        uint32[]  calldata successes,
        uint16[]  calldata slas
    ) external onlyUpdater {
        require(
            names.length == scores.length &&
            names.length == levels.length &&
            names.length == badges.length &&
            names.length == runs.length &&
            names.length == successes.length &&
            names.length == slas.length,
            "AgentRegistry: array length mismatch"
        );

        for (uint256 i = 0; i < names.length; i++) {
            if (agents[names[i]].registeredAt > 0) {
                uint16 oldScore = agents[names[i]].reputationScore;
                agents[names[i]].reputationScore = scores[i];
                agents[names[i]].level = levels[i];
                agents[names[i]].badge = badges[i];
                agents[names[i]].totalRuns = runs[i];
                agents[names[i]].successfulRuns = successes[i];
                agents[names[i]].slaPct = slas[i];
                agents[names[i]].lastUpdatedAt = uint64(block.timestamp);

                emit ReputationUpdated(
                    names[i], oldScore, scores[i], badges[i],
                    uint64(block.timestamp)
                );
            }
        }

        lastBatchUpdate = uint64(block.timestamp);
        emit BatchUpdateCompleted(names.length, uint64(block.timestamp));
    }

    // ============================================================
    // VERIFICATION RECEIPTS
    // ============================================================

    /**
     * @notice Record a verification receipt on-chain.
     */
    function recordVerification(
        bytes32 receiptHash,
        string calldata agentName,
        bool verified,
        uint16 confidence
    ) external onlyUpdater {
        receipts.push(VerificationReceipt({
            receiptHash: receiptHash,
            agentName: agentName,
            verified: verified,
            confidence: confidence,
            verifiedAt: uint64(block.timestamp)
        }));
        totalReceipts++;

        emit VerificationRecorded(
            receiptHash, agentName, verified, confidence,
            uint64(block.timestamp)
        );
    }

    // ============================================================
    // VIEWS
    // ============================================================

    function getAgent(string calldata name) external view returns (Agent memory) {
        return agents[name];
    }

    function getReputationScore(string calldata name) external view returns (uint16) {
        return agents[name].reputationScore;
    }

    function getBadge(string calldata name) external view returns (string memory) {
        return agents[name].badge;
    }

    function isActive(string calldata name) external view returns (bool) {
        return agents[name].active;
    }

    function getAgentCount() external view returns (uint256) {
        return totalAgents;
    }

    function getReceiptCount() external view returns (uint256) {
        return totalReceipts;
    }

    function getReceipt(uint256 index)
        external view returns (VerificationReceipt memory)
    {
        return receipts[index];
    }

    // ============================================================
    // ADMIN
    // ============================================================

    function setUpdater(address _updater) external onlyOwner {
        emit UpdaterChanged(updater, _updater);
        updater = _updater;
    }

    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "AgentRegistry: zero address");
        owner = newOwner;
    }
}
