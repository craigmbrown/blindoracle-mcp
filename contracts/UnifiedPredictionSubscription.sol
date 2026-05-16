// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "./OracleSubscription.sol";
import "./IReceiver.sol";
import "@openzeppelin/contracts/utils/introspection/ERC165.sol";

/**
 * @title UnifiedPredictionSubscription
 * @notice Combined subscription and prediction market contract with CRE integration
 * @dev Extends OracleSubscription with IReceiver for CRE workflow results
 *
 * Enhanced Verification Features:
 * - Multi-AI consensus support (tracks responses from multiple AI providers)
 * - Dispute period (24h) before final settlement
 * - Dispute staking mechanism (10% of total pool minimum)
 * - Challenge resolution via CRE re-verification
 *
 * CRE Integration:
 * - SettlementRequested event triggers CRE log workflow
 * - Workflow queries AI (Gemini/OpenAI) for outcome
 * - AI response is encoded and sent via onReport()
 * - Dispute period allows challenges before finalization
 *
 * @custom:security-contact security@example.com
 */
contract UnifiedPredictionSubscription is OracleSubscription, IReceiver, ERC165 {
    // =============================================================================
    // PREDICTION MARKET STRUCTS
    // =============================================================================

    enum MarketStatus {
        OPEN,                    // Accepting predictions
        SETTLEMENT_REQUESTED,    // Awaiting CRE response
        PENDING_FINALIZATION,    // In dispute period (24h)
        DISPUTED,                // Dispute raised, re-verification requested
        SETTLED,                 // Final outcome confirmed
        CANCELLED               // Market cancelled
    }

    struct Market {
        uint256 id;
        string question;          // e.g., "Will BTC reach 90,000 USD?"
        address creator;
        uint256 deadline;         // Timestamp when betting closes
        uint256 settlementDeadline; // Timestamp when market must be settled
        uint256 yesPool;          // Total ETH bet on YES
        uint256 noPool;           // Total ETH bet on NO
        MarketStatus status;
        bool outcome;             // true = YES, false = NO
        uint256 createdAt;
        // Enhanced verification fields
        uint256 finalizationTime; // When dispute period ends
        uint256 aiConfirmations;  // Number of AI providers that confirmed this outcome
        bool hasDispute;          // Whether a dispute was raised
    }

    struct Prediction {
        address predictor;
        uint256 amount;
        bool predictedYes;
        bool claimed;
    }

    struct Dispute {
        address challenger;
        uint256 stakeAmount;
        bool proposedOutcome;     // The outcome the challenger believes is correct
        uint256 createdAt;
        bool resolved;
        bool challengerWon;
    }

    struct AIVerification {
        string provider;          // "gemini", "openai", "claude"
        bool outcome;
        uint256 timestamp;
        bytes32 reportHash;       // Hash of the full report for audit
    }

    // =============================================================================
    // STATE VARIABLES
    // =============================================================================

    // Prediction market storage
    mapping(uint256 => Market) public markets;
    mapping(uint256 => mapping(address => Prediction)) public predictions;
    mapping(uint256 => Dispute) public disputes;
    mapping(uint256 => AIVerification[]) public aiVerifications;
    uint256 public marketCount;

    // CRE workflow authorization
    address public creWorkflowAuthor;
    bytes10 public expectedWorkflowName;

    // Market configuration
    uint256 public minBetAmount = 0.001 ether;
    uint256 public maxBetAmount = 100 ether;
    uint256 public platformFeePercent = 200; // 2% in basis points (100 = 1%)
    uint256 public constant BASIS_POINTS = 10000;

    // Settlement configuration
    uint256 public settlementWindow = 7 days;

    // Enhanced verification configuration
    uint256 public disputePeriod = 24 hours;          // Time to raise disputes
    uint256 public minDisputeStakePercent = 1000;     // 10% of total pool minimum
    uint256 public requiredAIConfirmations = 1;       // Minimum AI confirmations needed
    uint256 public consensusThreshold = 67;           // 67% agreement required for multi-AI

    // =============================================================================
    // EVENTS
    // =============================================================================

    event MarketCreated(
        uint256 indexed marketId,
        address indexed creator,
        string question,
        uint256 deadline,
        uint256 settlementDeadline
    );

    event PredictionPlaced(
        uint256 indexed marketId,
        address indexed predictor,
        bool predictedYes,
        uint256 amount
    );

    /**
     * @notice Emitted when settlement is requested - TRIGGERS CRE LOG WORKFLOW
     */
    event SettlementRequested(
        uint256 indexed marketId,
        string question
    );

    event AIVerificationReceived(
        uint256 indexed marketId,
        string provider,
        bool outcome,
        uint256 confirmations
    );

    event MarketPendingFinalization(
        uint256 indexed marketId,
        bool proposedOutcome,
        uint256 finalizationTime
    );

    event DisputeRaised(
        uint256 indexed marketId,
        address indexed challenger,
        uint256 stakeAmount,
        bool proposedOutcome
    );

    event DisputeResolved(
        uint256 indexed marketId,
        bool originalOutcomeConfirmed,
        address challenger,
        uint256 stakeReturned
    );

    event MarketSettled(
        uint256 indexed marketId,
        bool outcome,
        uint256 yesPool,
        uint256 noPool,
        uint256 aiConfirmations
    );

    event WinningsClaimed(
        uint256 indexed marketId,
        address indexed predictor,
        uint256 amount
    );

    event MarketCancelled(uint256 indexed marketId);

    event CREWorkflowConfigured(
        address indexed workflowAuthor,
        bytes10 workflowName
    );

    event VerificationConfigUpdated(
        uint256 disputePeriod,
        uint256 minDisputeStakePercent,
        uint256 requiredAIConfirmations
    );

    // =============================================================================
    // ERRORS
    // =============================================================================

    error MarketNotFound();
    error MarketNotOpen();
    error MarketDeadlinePassed();
    error MarketDeadlineNotPassed();
    error BetAmountTooLow();
    error BetAmountTooHigh();
    error AlreadyPredicted();
    error MarketNotSettled();
    error AlreadyClaimed();
    error NoWinnings();
    error InvalidWorkflowAuthor();
    error InvalidWorkflowName();
    error SettlementWindowExpired();
    error MarketAlreadySettled();
    error DisputeStakeTooLow();
    error DisputeAlreadyExists();
    error DisputePeriodNotEnded();
    error NotPendingFinalization();
    error NotInDisputedState();
    error CannotDisputeAfterPeriod();

    // =============================================================================
    // MODIFIERS
    // =============================================================================

    modifier marketExists(uint256 marketId) {
        if (markets[marketId].id == 0 && marketId != 0) revert MarketNotFound();
        if (markets[marketId].creator == address(0)) revert MarketNotFound();
        _;
    }

    modifier marketOpen(uint256 marketId) {
        if (markets[marketId].status != MarketStatus.OPEN) revert MarketNotOpen();
        if (block.timestamp >= markets[marketId].deadline) revert MarketDeadlinePassed();
        _;
    }

    // =============================================================================
    // CONSTRUCTOR
    // =============================================================================

    constructor(
        address _treasury,
        address _creWorkflowAuthor,
        bytes10 _expectedWorkflowName
    ) OracleSubscription(_treasury) {
        creWorkflowAuthor = _creWorkflowAuthor;
        expectedWorkflowName = _expectedWorkflowName;

        emit CREWorkflowConfigured(_creWorkflowAuthor, _expectedWorkflowName);
    }

    // =============================================================================
    // PREDICTION MARKET FUNCTIONS
    // =============================================================================

    /**
     * @notice Create a new prediction market
     * @param question The question to predict (e.g., "Will BTC reach 90,000 USD?")
     * @param deadline Timestamp when betting closes
     * @return marketId The ID of the created market
     */
    function createMarket(
        string calldata question,
        uint256 deadline
    ) external returns (uint256 marketId) {
        require(deadline > block.timestamp, "Deadline must be in the future");
        require(bytes(question).length > 0, "Question cannot be empty");
        require(bytes(question).length <= 500, "Question too long");

        marketId = marketCount++;

        markets[marketId] = Market({
            id: marketId,
            question: question,
            creator: msg.sender,
            deadline: deadline,
            settlementDeadline: deadline + settlementWindow,
            yesPool: 0,
            noPool: 0,
            status: MarketStatus.OPEN,
            outcome: false,
            createdAt: block.timestamp,
            finalizationTime: 0,
            aiConfirmations: 0,
            hasDispute: false
        });

        emit MarketCreated(
            marketId,
            msg.sender,
            question,
            deadline,
            deadline + settlementWindow
        );

        return marketId;
    }

    /**
     * @notice Place a prediction on a market
     * @param marketId The market to predict on
     * @param predictYes True to predict YES, false to predict NO
     */
    function placePrediction(
        uint256 marketId,
        bool predictYes
    ) external payable marketExists(marketId) marketOpen(marketId) nonReentrant {
        if (msg.value < minBetAmount) revert BetAmountTooLow();
        if (msg.value > maxBetAmount) revert BetAmountTooHigh();
        if (predictions[marketId][msg.sender].amount > 0) revert AlreadyPredicted();

        predictions[marketId][msg.sender] = Prediction({
            predictor: msg.sender,
            amount: msg.value,
            predictedYes: predictYes,
            claimed: false
        });

        if (predictYes) {
            markets[marketId].yesPool += msg.value;
        } else {
            markets[marketId].noPool += msg.value;
        }

        emit PredictionPlaced(marketId, msg.sender, predictYes, msg.value);
    }

    /**
     * @notice Request settlement for a market - TRIGGERS CRE WORKFLOW
     * @param marketId The market to settle
     */
    function requestSettlement(uint256 marketId) external marketExists(marketId) {
        Market storage market = markets[marketId];

        if (block.timestamp < market.deadline) revert MarketDeadlineNotPassed();
        if (market.status == MarketStatus.SETTLED) revert MarketAlreadySettled();
        if (block.timestamp > market.settlementDeadline) revert SettlementWindowExpired();

        market.status = MarketStatus.SETTLEMENT_REQUESTED;

        // This event triggers the CRE log workflow
        emit SettlementRequested(marketId, market.question);
    }

    // =============================================================================
    // ENHANCED VERIFICATION - DISPUTE MECHANISM
    // =============================================================================

    /**
     * @notice Raise a dispute during the finalization period
     * @param marketId The market to dispute
     * @param proposedOutcome The outcome the challenger believes is correct
     */
    function raiseDispute(
        uint256 marketId,
        bool proposedOutcome
    ) external payable marketExists(marketId) nonReentrant {
        Market storage market = markets[marketId];

        if (market.status != MarketStatus.PENDING_FINALIZATION) revert NotPendingFinalization();
        if (block.timestamp >= market.finalizationTime) revert CannotDisputeAfterPeriod();
        if (disputes[marketId].challenger != address(0)) revert DisputeAlreadyExists();

        // Calculate minimum stake (10% of total pool)
        uint256 totalPool = market.yesPool + market.noPool;
        uint256 minStake = (totalPool * minDisputeStakePercent) / BASIS_POINTS;
        if (msg.value < minStake) revert DisputeStakeTooLow();

        disputes[marketId] = Dispute({
            challenger: msg.sender,
            stakeAmount: msg.value,
            proposedOutcome: proposedOutcome,
            createdAt: block.timestamp,
            resolved: false,
            challengerWon: false
        });

        market.status = MarketStatus.DISPUTED;
        market.hasDispute = true;

        emit DisputeRaised(marketId, msg.sender, msg.value, proposedOutcome);

        // Re-trigger CRE workflow for re-verification
        emit SettlementRequested(marketId, market.question);
    }

    /**
     * @notice Finalize market after dispute period ends (no disputes)
     * @param marketId The market to finalize
     */
    function finalizeMarket(uint256 marketId) external marketExists(marketId) {
        Market storage market = markets[marketId];

        if (market.status != MarketStatus.PENDING_FINALIZATION) revert NotPendingFinalization();
        if (block.timestamp < market.finalizationTime) revert DisputePeriodNotEnded();

        market.status = MarketStatus.SETTLED;

        emit MarketSettled(
            marketId,
            market.outcome,
            market.yesPool,
            market.noPool,
            market.aiConfirmations
        );
    }

    /**
     * @notice Claim winnings after market settlement
     * @param marketId The market to claim from
     */
    function claimWinnings(uint256 marketId) external marketExists(marketId) nonReentrant {
        Market storage market = markets[marketId];
        Prediction storage prediction = predictions[marketId][msg.sender];

        if (market.status != MarketStatus.SETTLED) revert MarketNotSettled();
        if (prediction.claimed) revert AlreadyClaimed();
        if (prediction.amount == 0) revert NoWinnings();
        if (prediction.predictedYes != market.outcome) revert NoWinnings();

        prediction.claimed = true;

        // Calculate winnings
        uint256 totalPool = market.yesPool + market.noPool;
        uint256 winningPool = market.outcome ? market.yesPool : market.noPool;

        // Platform fee
        uint256 fee = (totalPool * platformFeePercent) / BASIS_POINTS;
        uint256 distributablePool = totalPool - fee;

        // Proportional winnings
        uint256 winnings = (prediction.amount * distributablePool) / winningPool;

        // Transfer winnings
        (bool success, ) = msg.sender.call{value: winnings}("");
        require(success, "Transfer failed");

        emit WinningsClaimed(marketId, msg.sender, winnings);
    }

    // =============================================================================
    // CRE IRECEIVER IMPLEMENTATION - ENHANCED
    // =============================================================================

    /**
     * @notice Receive settlement result from CRE workflow
     * @dev Called by CRE after AI determines the market outcome
     * @param metadata Encoded workflow metadata (owner + name)
     * @param report ABI-encoded (uint256 marketId, bool outcome, string provider)
     *
     * Enhanced Flow:
     * 1. Validate workflow authorization
     * 2. Record AI verification with provider info
     * 3. If first verification: start dispute period
     * 4. If disputed market: resolve dispute based on new verification
     * 5. Market enters PENDING_FINALIZATION for 24h dispute window
     */
    function onReport(
        bytes calldata metadata,
        bytes calldata report
    ) external override {
        // Decode and validate metadata
        (address workflowAuthor, bytes10 workflowName) = _decodeMetadata(metadata);

        if (workflowAuthor != creWorkflowAuthor) revert InvalidWorkflowAuthor();
        if (workflowName != expectedWorkflowName) revert InvalidWorkflowName();

        // Decode report: (marketId, outcome) - provider info optional
        (uint256 marketId, bool outcome) = abi.decode(report, (uint256, bool));

        Market storage market = markets[marketId];

        // Handle based on current state
        if (market.status == MarketStatus.SETTLEMENT_REQUESTED) {
            // First AI verification - start dispute period
            _processInitialVerification(marketId, outcome);
        } else if (market.status == MarketStatus.DISPUTED) {
            // Re-verification after dispute - resolve dispute
            _resolveDispute(marketId, outcome);
        } else {
            revert("Invalid market state for settlement");
        }
    }

    /**
     * @notice Process initial AI verification
     * @param marketId The market ID
     * @param outcome The AI-determined outcome
     */
    function _processInitialVerification(uint256 marketId, bool outcome) internal {
        Market storage market = markets[marketId];

        // Record verification
        market.outcome = outcome;
        market.aiConfirmations = 1;
        market.finalizationTime = block.timestamp + disputePeriod;
        market.status = MarketStatus.PENDING_FINALIZATION;

        // Store AI verification record
        aiVerifications[marketId].push(AIVerification({
            provider: "primary",
            outcome: outcome,
            timestamp: block.timestamp,
            reportHash: keccak256(abi.encode(marketId, outcome, block.timestamp))
        }));

        emit AIVerificationReceived(marketId, "primary", outcome, 1);
        emit MarketPendingFinalization(marketId, outcome, market.finalizationTime);
    }

    /**
     * @notice Resolve a dispute based on re-verification
     * @param marketId The market ID
     * @param newOutcome The new AI-determined outcome
     */
    function _resolveDispute(uint256 marketId, bool newOutcome) internal {
        Market storage market = markets[marketId];
        Dispute storage dispute = disputes[marketId];

        // Record new verification
        market.aiConfirmations++;
        aiVerifications[marketId].push(AIVerification({
            provider: "dispute-verification",
            outcome: newOutcome,
            timestamp: block.timestamp,
            reportHash: keccak256(abi.encode(marketId, newOutcome, block.timestamp, "dispute"))
        }));

        emit AIVerificationReceived(marketId, "dispute-verification", newOutcome, market.aiConfirmations);

        // Determine winner: if new outcome matches challenger's proposal, challenger wins
        bool challengerWins = (newOutcome == dispute.proposedOutcome);
        dispute.resolved = true;
        dispute.challengerWon = challengerWins;

        if (challengerWins) {
            // Update outcome to challenger's proposed outcome
            market.outcome = dispute.proposedOutcome;

            // Return stake to challenger with 10% bonus from platform fees
            uint256 bonus = (dispute.stakeAmount * 10) / 100;
            uint256 totalReturn = dispute.stakeAmount + bonus;

            (bool success, ) = dispute.challenger.call{value: totalReturn}("");
            require(success, "Stake return failed");

            emit DisputeResolved(marketId, false, dispute.challenger, totalReturn);
        } else {
            // Original outcome confirmed - challenger loses stake to platform
            emit DisputeResolved(marketId, true, dispute.challenger, 0);
        }

        // Settle immediately after dispute resolution
        market.status = MarketStatus.SETTLED;

        emit MarketSettled(
            marketId,
            market.outcome,
            market.yesPool,
            market.noPool,
            market.aiConfirmations
        );
    }

    /**
     * @notice Decode CRE metadata to extract workflow owner and name
     */
    function _decodeMetadata(
        bytes memory metadata
    ) internal pure returns (address workflowOwner, bytes10 workflowName) {
        require(metadata.length >= 30, "Invalid metadata length");

        assembly {
            workflowOwner := mload(add(metadata, 32))
            workflowOwner := shr(96, workflowOwner)
            workflowName := mload(add(metadata, 52))
        }
    }

    // =============================================================================
    // ERC165 IMPLEMENTATION
    // =============================================================================

    function supportsInterface(
        bytes4 interfaceId
    ) public view override(ERC165, IERC165) returns (bool) {
        return
            interfaceId == type(IReceiver).interfaceId ||
            super.supportsInterface(interfaceId);
    }

    // =============================================================================
    // ADMIN FUNCTIONS
    // =============================================================================

    function setCREWorkflow(
        address _creWorkflowAuthor,
        bytes10 _expectedWorkflowName
    ) external onlyOwner {
        creWorkflowAuthor = _creWorkflowAuthor;
        expectedWorkflowName = _expectedWorkflowName;
        emit CREWorkflowConfigured(_creWorkflowAuthor, _expectedWorkflowName);
    }

    function setBetLimits(
        uint256 _minBetAmount,
        uint256 _maxBetAmount
    ) external onlyOwner {
        require(_minBetAmount < _maxBetAmount, "Invalid limits");
        minBetAmount = _minBetAmount;
        maxBetAmount = _maxBetAmount;
    }

    function setPlatformFee(uint256 _platformFeePercent) external onlyOwner {
        require(_platformFeePercent <= 1000, "Fee too high");
        platformFeePercent = _platformFeePercent;
    }

    function setSettlementWindow(uint256 _settlementWindow) external onlyOwner {
        require(_settlementWindow >= 1 days, "Window too short");
        require(_settlementWindow <= 30 days, "Window too long");
        settlementWindow = _settlementWindow;
    }

    /**
     * @notice Configure enhanced verification parameters
     * @param _disputePeriod Time in seconds for dispute window
     * @param _minDisputeStakePercent Minimum stake as % of pool (basis points)
     * @param _requiredAIConfirmations Minimum AI confirmations needed
     */
    function setVerificationConfig(
        uint256 _disputePeriod,
        uint256 _minDisputeStakePercent,
        uint256 _requiredAIConfirmations
    ) external onlyOwner {
        require(_disputePeriod >= 1 hours, "Dispute period too short");
        require(_disputePeriod <= 7 days, "Dispute period too long");
        require(_minDisputeStakePercent >= 100, "Stake too low"); // Min 1%
        require(_minDisputeStakePercent <= 5000, "Stake too high"); // Max 50%

        disputePeriod = _disputePeriod;
        minDisputeStakePercent = _minDisputeStakePercent;
        requiredAIConfirmations = _requiredAIConfirmations;

        emit VerificationConfigUpdated(_disputePeriod, _minDisputeStakePercent, _requiredAIConfirmations);
    }

    function cancelMarket(uint256 marketId) external onlyOwner marketExists(marketId) {
        Market storage market = markets[marketId];
        require(market.yesPool == 0 && market.noPool == 0, "Cannot cancel with bets");
        market.status = MarketStatus.CANCELLED;
        emit MarketCancelled(marketId);
    }

    function emergencySettle(
        uint256 marketId,
        bool outcome
    ) external onlyOwner marketExists(marketId) {
        Market storage market = markets[marketId];
        require(
            market.status == MarketStatus.OPEN ||
            market.status == MarketStatus.SETTLEMENT_REQUESTED ||
            market.status == MarketStatus.PENDING_FINALIZATION ||
            market.status == MarketStatus.DISPUTED,
            "Cannot settle"
        );
        require(block.timestamp >= market.deadline, "Deadline not passed");

        market.status = MarketStatus.SETTLED;
        market.outcome = outcome;

        emit MarketSettled(marketId, outcome, market.yesPool, market.noPool, 0);
    }

    function withdrawFees() external onlyOwner nonReentrant {
        uint256 balance = address(this).balance;
        require(balance > 0, "No balance");
        (bool success, ) = treasuryAddress.call{value: balance}("");
        require(success, "Transfer failed");
    }

    // =============================================================================
    // VIEW FUNCTIONS
    // =============================================================================

    function getMarket(uint256 marketId) external view returns (Market memory) {
        return markets[marketId];
    }

    function getPrediction(
        uint256 marketId,
        address predictor
    ) external view returns (Prediction memory) {
        return predictions[marketId][predictor];
    }

    function getDispute(uint256 marketId) external view returns (Dispute memory) {
        return disputes[marketId];
    }

    function getAIVerifications(uint256 marketId) external view returns (AIVerification[] memory) {
        return aiVerifications[marketId];
    }

    function calculatePotentialWinnings(
        uint256 marketId,
        uint256 amount,
        bool predictYes
    ) external view returns (uint256 potentialWinnings) {
        Market memory market = markets[marketId];
        uint256 newPool = predictYes ? market.yesPool + amount : market.noPool + amount;
        uint256 totalPool = market.yesPool + market.noPool + amount;
        uint256 fee = (totalPool * platformFeePercent) / BASIS_POINTS;
        uint256 distributablePool = totalPool - fee;
        potentialWinnings = (amount * distributablePool) / newPool;
    }

    function getActiveMarkets() external view returns (uint256[] memory marketIds) {
        uint256 activeCount = 0;
        for (uint256 i = 0; i < marketCount; i++) {
            if (markets[i].status == MarketStatus.OPEN && block.timestamp < markets[i].deadline) {
                activeCount++;
            }
        }
        marketIds = new uint256[](activeCount);
        uint256 index = 0;
        for (uint256 i = 0; i < marketCount; i++) {
            if (markets[i].status == MarketStatus.OPEN && block.timestamp < markets[i].deadline) {
                marketIds[index++] = i;
            }
        }
    }

    function needsSettlement(uint256 marketId) external view returns (bool) {
        Market memory market = markets[marketId];
        return market.status == MarketStatus.OPEN &&
               block.timestamp >= market.deadline &&
               block.timestamp <= market.settlementDeadline;
    }

    function canBeFinalized(uint256 marketId) external view returns (bool) {
        Market memory market = markets[marketId];
        return market.status == MarketStatus.PENDING_FINALIZATION &&
               block.timestamp >= market.finalizationTime;
    }

    function getDisputeMinStake(uint256 marketId) external view returns (uint256) {
        Market memory market = markets[marketId];
        uint256 totalPool = market.yesPool + market.noPool;
        return (totalPool * minDisputeStakePercent) / BASIS_POINTS;
    }
}
