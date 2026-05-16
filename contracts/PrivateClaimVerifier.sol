// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/security/ReentrancyGuard.sol";

/**
 * @title PrivateClaimVerifier
 * @notice Anonymous commitment-based predictions and claims for BlindOracle privacy prediction markets
 * @dev Works alongside UnifiedPredictionSubscription to add a privacy layer using commit-reveal scheme
 *
 * Privacy Design:
 * - At bet time: User submits commitment = keccak256(secret || position || amount)
 * - At claim time: User reveals secret, contract verifies keccak256(secret, position, amount) == stored commitment
 * - No identity link: The claiming address does not need to match the betting address
 * - The contract does NOT know which position (YES/NO) a commitment represents until claim time
 * - Observers see deposits but cannot determine positions -- this is the core privacy feature
 *
 * Pools (marketYesPool / marketNoPool) are NOT updated at deposit time because the position
 * is hidden inside the commitment. They are only updated at claim time when the position is revealed.
 * Total deposits per market are tracked separately for proportional winnings calculation.
 *
 * @custom:security-contact security@example.com
 */
contract PrivateClaimVerifier is Ownable, ReentrancyGuard {
    // =============================================================================
    // STRUCTS
    // =============================================================================

    struct PrivatePosition {
        bytes32 commitment;      // keccak256(secret || position || amount)
        uint256 marketId;        // Links to UnifiedPredictionSubscription market
        uint256 depositAmount;   // Amount deposited (in wei)
        uint256 depositTime;     // Block timestamp of deposit
        bool claimed;            // Whether winnings have been claimed
        bool refunded;           // Whether deposit was refunded (cancelled market)
    }

    struct ClaimProof {
        bytes32 secret;          // The secret used in commitment
        bool position;           // true = YES, false = NO
        uint256 amount;          // Must match depositAmount
    }

    // =============================================================================
    // ENUMS
    // =============================================================================

    enum MarketOutcomeStatus {
        PENDING,     // Outcome not yet determined
        RESOLVED,    // Outcome has been set
        CANCELLED    // Market was cancelled, deposits can be refunded
    }

    struct MarketOutcome {
        MarketOutcomeStatus status;
        bool outcome;            // true = YES won, false = NO won (only valid when RESOLVED)
    }

    // =============================================================================
    // STATE VARIABLES
    // =============================================================================

    /// @notice Commitment -> private position data
    mapping(bytes32 => PrivatePosition) public positions;

    /// @notice Market ID -> list of commitments submitted for that market
    mapping(uint256 => bytes32[]) public marketCommitments;

    /// @notice Market ID -> total YES deposits (updated at claim time only)
    mapping(uint256 => uint256) public marketYesPool;

    /// @notice Market ID -> total NO deposits (updated at claim time only)
    mapping(uint256 => uint256) public marketNoPool;

    /// @notice Market ID -> total deposits (updated at deposit time, used for proportional winnings)
    mapping(uint256 => uint256) public marketTotalDeposits;

    /// @notice Market ID -> outcome information
    mapping(uint256 => MarketOutcome) public marketOutcomes;

    // --- Two-phase reveal+claim state (fix for critical payout bug) ---

    /// @notice Commitment -> whether the position has been revealed (phase 1)
    mapping(bytes32 => bool) public revealed;

    /// @notice Market ID -> locked winning pool total (set by finalizeWinningPool)
    mapping(uint256 => uint256) public marketFinalWinningPool;

    /// @notice Market ID -> whether the claim phase is open (pool is finalized and locked)
    mapping(uint256 => bool) public marketClaimPhaseOpen;

    /// @notice Address of the UnifiedPredictionSubscription contract
    address public predictionMarket;

    /// @notice Platform fee in basis points (200 = 2%)
    uint256 public platformFeePercent = 200;

    /// @notice Basis points denominator
    uint256 public constant BASIS_POINTS = 10000;

    /// @notice Minimum deposit amount in wei (0.001 ETH — prevents dust attacks)
    uint256 public constant MIN_DEPOSIT = 1e15;

    /// @notice Maximum commitments per market to prevent gas DoS on resolution
    uint256 public constant MAX_COMMITMENTS_PER_MARKET = 10_000;

    // =============================================================================
    // EVENTS
    // =============================================================================

    event CommitmentSubmitted(
        bytes32 indexed commitment,
        uint256 indexed marketId,
        uint256 amount
    );

    event WinningsClaimed(
        bytes32 indexed commitment,
        uint256 indexed marketId,
        uint256 amount
    );

    event DepositRefunded(
        bytes32 indexed commitment,
        uint256 indexed marketId,
        uint256 amount
    );

    event MarketOutcomeSet(
        uint256 indexed marketId,
        bool outcome
    );

    event MarketCancelled(
        uint256 indexed marketId
    );

    event PredictionMarketUpdated(
        address indexed newPredictionMarket
    );

    event PlatformFeeUpdated(
        uint256 newFeePercent
    );

    event PositionRevealed(
        bytes32 indexed commitment,
        uint256 indexed marketId,
        bool position,
        uint256 amount
    );

    event WinningPoolFinalized(
        uint256 indexed marketId,
        uint256 winningPool
    );

    // =============================================================================
    // ERRORS
    // =============================================================================

    error CommitmentAlreadyUsed();
    error DepositTooLow();
    error MarketNotResolved();
    error MarketNotCancelled();
    error MarketAlreadyResolved();
    error CommitmentMismatch();
    error PositionDidNotWin();
    error AlreadyClaimed();
    error AlreadyRefunded();
    error TransferFailed();
    error NotAuthorized();
    error InvalidCommitment();
    error FeeTooHigh();
    error NoDepositsInMarket();
    error ClaimPhaseNotOpen();
    error AlreadyRevealed();
    error MarketAtCapacity();
    error WinningPoolIsZero();

    // =============================================================================
    // MODIFIERS
    // =============================================================================

    modifier onlyAuthorized() {
        if (msg.sender != owner() && msg.sender != predictionMarket) {
            revert NotAuthorized();
        }
        _;
    }

    // =============================================================================
    // CONSTRUCTOR
    // =============================================================================

    /**
     * @notice Deploy the PrivateClaimVerifier
     * @param _predictionMarket Address of the UnifiedPredictionSubscription contract
     */
    constructor(address _predictionMarket) Ownable() {
        predictionMarket = _predictionMarket;

        emit PredictionMarketUpdated(_predictionMarket);
    }

    // =============================================================================
    // CORE FUNCTIONS
    // =============================================================================

    /**
     * @notice Submit a commitment to a private position in a prediction market
     * @dev The commitment hides the user's position (YES/NO). The contract only learns
     *      the position at claim time when the secret is revealed.
     *      Commitment format: keccak256(abi.encodePacked(secret, position, amount))
     *      where amount must equal msg.value.
     * @param commitment The keccak256 hash of (secret, position, amount)
     * @param marketId The prediction market to participate in
     */
    function submitCommitment(
        bytes32 commitment,
        uint256 marketId
    ) external payable {
        // Validate commitment is not zero
        if (commitment == bytes32(0)) revert InvalidCommitment();

        // Validate commitment has not been used before
        if (positions[commitment].depositAmount != 0) revert CommitmentAlreadyUsed();

        // Validate deposit meets minimum
        if (msg.value < MIN_DEPOSIT) revert DepositTooLow();

        // Enforce commitment cap to prevent gas DoS on resolution
        if (marketCommitments[marketId].length >= MAX_COMMITMENTS_PER_MARKET) revert MarketAtCapacity();

        // Validate market outcome has not already been set
        if (marketOutcomes[marketId].status != MarketOutcomeStatus.PENDING) {
            revert MarketAlreadyResolved();
        }

        // Store the private position
        positions[commitment] = PrivatePosition({
            commitment: commitment,
            marketId: marketId,
            depositAmount: msg.value,
            depositTime: block.timestamp,
            claimed: false,
            refunded: false
        });

        // Track commitment for this market
        marketCommitments[marketId].push(commitment);

        // Track total deposits for the market (position-agnostic at this point)
        marketTotalDeposits[marketId] += msg.value;

        emit CommitmentSubmitted(commitment, marketId, msg.value);
    }

    /**
     * @notice Phase 1 — Reveal a winning position to register it in the winning pool.
     * @dev Winners MUST call revealPosition() during the reveal window, before the operator
     *      calls finalizeWinningPool(). This builds the correct denominator for payout.
     *      The claiming address does NOT need to match the depositing address.
     *      Losers do not need to reveal — only the winning side participates.
     * @param secret The secret used when creating the commitment
     * @param position true = YES, false = NO
     * @param amount The original deposit amount (must match stored depositAmount)
     * @param marketId The market to reveal for
     */
    function revealPosition(
        bytes32 secret,
        bool position,
        uint256 amount,
        uint256 marketId
    ) external {
        // Reconstruct and validate commitment
        bytes32 commitment = verifyCommitment(secret, position, amount);

        PrivatePosition storage pos = positions[commitment];
        if (pos.depositAmount == 0) revert CommitmentMismatch();
        if (pos.depositAmount != amount) revert CommitmentMismatch();
        if (pos.marketId != marketId) revert CommitmentMismatch();
        if (pos.claimed) revert AlreadyClaimed();
        if (pos.refunded) revert AlreadyRefunded();
        if (revealed[commitment]) revert AlreadyRevealed();

        // Market must be resolved before reveal
        MarketOutcome memory outcome = marketOutcomes[marketId];
        if (outcome.status != MarketOutcomeStatus.RESOLVED) revert MarketNotResolved();

        // Only winning positions reveal (losers forfeit — their deposits fund winners)
        if (position != outcome.outcome) revert PositionDidNotWin();

        // Claim phase must NOT be open yet (reveals happen before finalization)
        if (marketClaimPhaseOpen[marketId]) revert ClaimPhaseNotOpen();

        // Mark revealed and accumulate winning pool
        revealed[commitment] = true;

        if (position) {
            marketYesPool[marketId] += amount;
        } else {
            marketNoPool[marketId] += amount;
        }

        emit PositionRevealed(commitment, marketId, position, amount);
    }

    /**
     * @notice Finalize the winning pool for a market, locking it and opening the claim phase.
     * @dev Called by the operator after the reveal window closes. Locks the winning pool total
     *      so that claimWinnings() has a stable denominator. Cannot be undone.
     *      Requires at least one position to have been revealed.
     * @param marketId The market to finalize
     */
    function finalizeWinningPool(uint256 marketId) external onlyAuthorized {
        if (marketClaimPhaseOpen[marketId]) revert MarketAlreadyResolved();

        MarketOutcome memory outcome = marketOutcomes[marketId];
        if (outcome.status != MarketOutcomeStatus.RESOLVED) revert MarketNotResolved();

        uint256 winningPool = outcome.outcome
            ? marketYesPool[marketId]
            : marketNoPool[marketId];

        if (winningPool == 0) revert WinningPoolIsZero();

        marketFinalWinningPool[marketId] = winningPool;
        marketClaimPhaseOpen[marketId] = true;

        emit WinningPoolFinalized(marketId, winningPool);
    }

    /**
     * @notice Phase 2 — Claim winnings after the winning pool has been finalized.
     * @dev Requires that the caller previously called revealPosition() and that the
     *      operator has called finalizeWinningPool(). Uses the locked winning pool as
     *      denominator so all claimants receive the same proportional share.
     *
     *      Payout formula (correct):
     *        winnings = (depositAmount / finalWinningPool) * distributablePool
     *
     * @param secret The secret used when creating the commitment
     * @param position true = YES, false = NO
     * @param amount The original deposit amount (must match stored depositAmount)
     * @param marketId The market to claim from
     */
    function claimWinnings(
        bytes32 secret,
        bool position,
        uint256 amount,
        uint256 marketId
    ) external nonReentrant {
        // Reconstruct the commitment from the revealed parameters
        bytes32 commitment = verifyCommitment(secret, position, amount);

        // Validate the commitment exists and matches
        PrivatePosition storage pos = positions[commitment];
        if (pos.depositAmount == 0) revert CommitmentMismatch();
        if (pos.depositAmount != amount) revert CommitmentMismatch();
        if (pos.marketId != marketId) revert CommitmentMismatch();
        if (pos.claimed) revert AlreadyClaimed();
        if (pos.refunded) revert AlreadyRefunded();

        // Claim phase must be open (operator has finalized the winning pool)
        if (!marketClaimPhaseOpen[marketId]) revert ClaimPhaseNotOpen();

        // Position must have been revealed in phase 1
        if (!revealed[commitment]) revert AlreadyRevealed();

        // Validate the market has been resolved and position is a winner
        MarketOutcome memory outcome = marketOutcomes[marketId];
        if (outcome.status != MarketOutcomeStatus.RESOLVED) revert MarketNotResolved();
        if (position != outcome.outcome) revert PositionDidNotWin();

        // Mark as claimed (effects before interactions)
        pos.claimed = true;

        // Calculate winnings using the locked winning pool as denominator.
        // BUG FIX: Previous code used totalDeposits as denominator, which
        // paid each winner only their proportional share of the total pool —
        // losers' funds were never distributed. The correct formula divides
        // the distributable pool by the WINNING pool so that winners share
        // all the losing deposits proportionally.
        uint256 totalDeposits = marketTotalDeposits[marketId];
        if (totalDeposits == 0) revert NoDepositsInMarket();

        uint256 fee = (totalDeposits * platformFeePercent) / BASIS_POINTS;
        uint256 distributablePool = totalDeposits - fee;

        uint256 winningPool = marketFinalWinningPool[marketId];
        // winningPool > 0 is guaranteed by finalizeWinningPool() check above

        // Correct proportional payout: winner's share of all deposits (minus fee)
        uint256 winnings = (amount * distributablePool) / winningPool;

        // Transfer winnings
        (bool success, ) = msg.sender.call{value: winnings}("");
        if (!success) revert TransferFailed();

        emit WinningsClaimed(commitment, marketId, winnings);
    }

    /**
     * @notice Refund a deposit for a cancelled market
     * @dev Same commitment verification as claimWinnings but returns the original deposit amount
     * @param secret The secret used when creating the commitment
     * @param position true = YES, false = NO
     * @param amount The original deposit amount
     * @param marketId The market to get a refund from
     */
    function refundDeposit(
        bytes32 secret,
        bool position,
        uint256 amount,
        uint256 marketId
    ) external nonReentrant {
        // Reconstruct the commitment from the revealed parameters
        bytes32 commitment = verifyCommitment(secret, position, amount);

        // Validate the commitment exists and matches
        PrivatePosition storage pos = positions[commitment];
        if (pos.depositAmount == 0) revert CommitmentMismatch();
        if (pos.depositAmount != amount) revert CommitmentMismatch();
        if (pos.marketId != marketId) revert CommitmentMismatch();
        if (pos.claimed) revert AlreadyClaimed();
        if (pos.refunded) revert AlreadyRefunded();

        // Validate the market has been cancelled
        MarketOutcome memory outcome = marketOutcomes[marketId];
        if (outcome.status != MarketOutcomeStatus.CANCELLED) revert MarketNotCancelled();

        // Mark as refunded (effects before interactions)
        pos.refunded = true;

        // Reduce total deposits tracking
        marketTotalDeposits[marketId] -= amount;

        // Transfer original deposit back
        (bool success, ) = msg.sender.call{value: amount}("");
        if (!success) revert TransferFailed();

        emit DepositRefunded(commitment, marketId, amount);
    }

    // =============================================================================
    // COMMITMENT VERIFICATION
    // =============================================================================

    /**
     * @notice Helper to compute a commitment hash from its components
     * @dev Useful for off-chain commitment generation and verification.
     *      Users should call this function off-chain before submitting to ensure
     *      their commitment is correctly formed.
     * @param secret The secret value (should be randomly generated off-chain)
     * @param position true = YES, false = NO
     * @param amount The deposit amount in wei
     * @return The keccak256 hash commitment
     */
    function verifyCommitment(
        bytes32 secret,
        bool position,
        uint256 amount
    ) public pure returns (bytes32) {
        return keccak256(abi.encodePacked(secret, position, amount));
    }

    // =============================================================================
    // MARKET OUTCOME MANAGEMENT
    // =============================================================================

    /**
     * @notice Set the outcome of a market after settlement
     * @dev Only callable by the contract owner or the linked prediction market contract.
     *      This bridges the outcome from UnifiedPredictionSubscription into the
     *      private claim system.
     * @param marketId The market to set the outcome for
     * @param outcome true = YES outcome, false = NO outcome
     */
    function setMarketOutcome(
        uint256 marketId,
        bool outcome
    ) external onlyAuthorized {
        MarketOutcome storage mo = marketOutcomes[marketId];
        if (mo.status != MarketOutcomeStatus.PENDING) revert MarketAlreadyResolved();

        mo.status = MarketOutcomeStatus.RESOLVED;
        mo.outcome = outcome;

        emit MarketOutcomeSet(marketId, outcome);
    }

    /**
     * @notice Cancel a market, allowing all depositors to reclaim their funds
     * @dev Only callable by the contract owner or the linked prediction market contract
     * @param marketId The market to cancel
     */
    function cancelMarket(
        uint256 marketId
    ) external onlyAuthorized {
        MarketOutcome storage mo = marketOutcomes[marketId];
        if (mo.status == MarketOutcomeStatus.RESOLVED) revert MarketAlreadyResolved();

        mo.status = MarketOutcomeStatus.CANCELLED;

        emit MarketCancelled(marketId);
    }

    // =============================================================================
    // VIEW FUNCTIONS
    // =============================================================================

    /**
     * @notice Get aggregate statistics for a market
     * @param marketId The market to query
     * @return totalCommitments Number of commitments submitted
     * @return totalDeposited Total wei deposited
     * @return claimPhaseOpen Whether the claim phase is open (winning pool finalized)
     * @return finalWinningPool The locked winning pool (0 until finalized)
     */
    function getMarketStats(
        uint256 marketId
    ) external view returns (
        uint256 totalCommitments,
        uint256 totalDeposited,
        bool claimPhaseOpen,
        uint256 finalWinningPool
    ) {
        totalCommitments = marketCommitments[marketId].length;
        totalDeposited = marketTotalDeposits[marketId];
        claimPhaseOpen = marketClaimPhaseOpen[marketId];
        finalWinningPool = marketFinalWinningPool[marketId];
    }

    /**
     * @notice Get the list of commitments for a market
     * @dev Returns only the commitment hashes -- no position information is revealed
     * @param marketId The market to query
     * @return commitments Array of commitment hashes
     */
    function getMarketCommitments(
        uint256 marketId
    ) external view returns (bytes32[] memory commitments) {
        return marketCommitments[marketId];
    }

    /**
     * @notice Get the revealed pool sizes for a market
     * @dev These values are only populated as winners claim. Before claims,
     *      both values will be zero even if there are deposits.
     * @param marketId The market to query
     * @return yesPool Total deposits revealed as YES positions
     * @return noPool Total deposits revealed as NO positions
     */
    function getRevealedPools(
        uint256 marketId
    ) external view returns (
        uint256 yesPool,
        uint256 noPool
    ) {
        yesPool = marketYesPool[marketId];
        noPool = marketNoPool[marketId];
    }

    /**
     * @notice Check if a commitment exists and its status
     * @param commitment The commitment hash to check
     * @return exists Whether the commitment exists
     * @return claimed Whether winnings have been claimed
     * @return refunded Whether the deposit was refunded
     * @return depositAmount The deposit amount in wei
     */
    function getCommitmentStatus(
        bytes32 commitment
    ) external view returns (
        bool exists,
        bool claimed,
        bool refunded,
        uint256 depositAmount
    ) {
        PrivatePosition memory pos = positions[commitment];
        exists = pos.depositAmount > 0;
        claimed = pos.claimed;
        refunded = pos.refunded;
        depositAmount = pos.depositAmount;
    }

    // =============================================================================
    // ADMIN FUNCTIONS
    // =============================================================================

    /**
     * @notice Update the linked prediction market contract address
     * @param _predictionMarket New prediction market address
     */
    function setPredictionMarket(address _predictionMarket) external onlyOwner {
        predictionMarket = _predictionMarket;

        emit PredictionMarketUpdated(_predictionMarket);
    }

    /**
     * @notice Update the platform fee percentage
     * @param _platformFeePercent New fee in basis points (max 1000 = 10%)
     */
    function setPlatformFee(uint256 _platformFeePercent) external onlyOwner {
        if (_platformFeePercent > 1000) revert FeeTooHigh();
        platformFeePercent = _platformFeePercent;

        emit PlatformFeeUpdated(_platformFeePercent);
    }

    /**
     * @notice Withdraw accumulated platform fees (unclaimed losing deposits)
     * @dev Only withdraws funds not reserved for pending claims or refunds.
     *      In practice, this should only be called after all winning claims
     *      and refunds for a market have been processed.
     * @param to Address to send fees to
     * @param amount Amount to withdraw in wei
     */
    function withdrawFees(address to, uint256 amount) external onlyOwner nonReentrant {
        require(to != address(0), "Invalid recipient");
        require(amount <= address(this).balance, "Insufficient balance");

        (bool success, ) = to.call{value: amount}("");
        if (!success) revert TransferFailed();
    }

    /// @notice Allow the contract to receive ETH directly (for edge cases)
    receive() external payable {}
}

// =============================================================================
// TEST SCENARIOS (two-phase reveal+claim model)
// =============================================================================
//
// HAPPY PATH: Full two-phase flow
//
// 1. Submit -> reveal -> finalize -> claim (correct) -> SUCCESS
//    a. Alice: secret=S, commitment = keccak256(S, true, 1 ether)
//    b. Alice: submitCommitment(commitment, marketId) with 1 ether
//    c. Operator: setMarketOutcome(marketId, true)   // YES wins
//    d. Alice: revealPosition(S, true, 1 ether, marketId)  // registers in winning pool
//    e. Operator: finalizeWinningPool(marketId)            // locks pool, opens claims
//    f. Alice: claimWinnings(S, true, 1 ether, marketId)   // receives payout
//
// 2. Correct payout math: 2 winners, 1 loser, 2% fee
//    - Alice: 1 ETH YES, Bob: 1 ETH YES, Carol: 2 ETH NO
//    - totalDeposits = 4 ETH, fee = 0.08 ETH, distributablePool = 3.92 ETH
//    - winningPool = 2 ETH (Alice + Bob)
//    - Alice payout = (1 / 2) * 3.92 = 1.96 ETH  ✓ (gets back deposit + half of loser funds)
//    - Bob payout   = (1 / 2) * 3.92 = 1.96 ETH  ✓
//    - Carol: PositionDidNotWin() — cannot claim
//
// ERROR CASES:
//
// 3. Claim before reveal -> FAIL
//    - Alice submits, market resolves, finalized, but Alice never called revealPosition()
//    - Alice calls claimWinnings() -> AlreadyRevealed() revert (not revealed)
//
// 4. Claim before finalization -> FAIL
//    - Alice submits, market resolves, Alice reveals, but operator has NOT finalized
//    - Alice calls claimWinnings() -> ClaimPhaseNotOpen() revert
//
// 5. Reveal after finalization -> FAIL
//    - Operator finalizes pool, then Alice tries to reveal
//    - Alice calls revealPosition() -> ClaimPhaseNotOpen() revert
//
// 6. Double-reveal -> FAIL
//    - Alice reveals once successfully
//    - Alice tries to reveal again -> AlreadyRevealed() revert
//
// 7. Double-claim -> FAIL
//    - Alice claims once successfully
//    - Alice tries to claim again -> AlreadyClaimed() revert
//
// 8. Wrong secret -> FAIL (commitment mismatch)
//    - Alice submitted with secret_A, tries claimWinnings with secret_B
//    - CommitmentMismatch() revert
//
// 9. Privacy: claim from different address -> SUCCESS
//    - Alice submits from address_A, reveals from address_A
//    - Alice claims from address_B with correct secret -> SUCCESS
//    - No on-chain link between address_A and address_B
//
// 10. Cancelled market -> refund, not claim
//     - Market cancelled via cancelMarket()
//     - Alice: refundDeposit(S, true, 1 ether, marketId) -> gets deposit back
//     - Alice: claimWinnings() -> MarketNotResolved() revert
//
// 11. Dust attack prevention
//     - Alice calls submitCommitment() with msg.value < 1e15 -> DepositTooLow() revert
//
// 12. Gas DoS prevention
//     - 10,001st commitment on same market -> MarketAtCapacity() revert
//
// 13. finalize with zero winning reveals -> FAIL
//     - No winners called revealPosition() before operator calls finalizeWinningPool()
//     - WinningPoolIsZero() revert — prevents market where all losers drain the pool
