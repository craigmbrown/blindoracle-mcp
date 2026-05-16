// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/security/ReentrancyGuard.sol";
import "@openzeppelin/contracts/security/Pausable.sol";

/**
 * @title OracleSubscription
 * @notice Chainlink CRE-compatible subscription contract for Oracle API Service
 * @dev Manages ERC20 subscription payments with on-chain access control
 *
 * Features:
 * - ERC20 payments (USDC, USDT, DAI, LINK)
 * - 4 subscription tiers (Free, Basic, Pro, Enterprise)
 * - On-chain API key validation
 * - Auto-renewal support via CRE CRON
 * - Revenue withdrawal to Fedimint bridge
 *
 * @custom:security-contact security@example.com
 */
contract OracleSubscription is Ownable, ReentrancyGuard, Pausable {
    using SafeERC20 for IERC20;

    // =============================================================================
    // ENUMS & STRUCTS
    // =============================================================================

    enum SubscriptionTier { FREE, BASIC, PRO, ENTERPRISE }
    enum SubscriptionStatus { INACTIVE, ACTIVE, EXPIRED, CANCELLED }

    struct Subscription {
        address subscriber;
        SubscriptionTier tier;
        SubscriptionStatus status;
        uint256 startTime;
        uint256 expiresAt;
        uint256 callsPerMonth;
        uint256 callsUsed;
        bytes32 apiKeyHash;  // Hash of API key for on-chain validation
        address paymentToken;
        uint256 amountPaid;
        bool autoRenew;
    }

    struct TierConfig {
        uint256 priceUSD;      // Price in USD (6 decimals for USDC compatibility)
        uint256 callsPerMonth;
        uint256 ratePerMinute;
        bool active;
    }

    // =============================================================================
    // STATE VARIABLES
    // =============================================================================

    // Subscription storage
    mapping(address => Subscription) public subscriptions;
    mapping(bytes32 => address) public apiKeyToSubscriber;  // API key hash -> subscriber

    // Tier configurations
    mapping(SubscriptionTier => TierConfig) public tierConfigs;

    // Accepted payment tokens (USDC, USDT, DAI, LINK)
    mapping(address => bool) public acceptedTokens;
    address[] public tokenList;

    // Revenue management
    address public treasuryAddress;  // Fedimint bridge or multi-sig
    uint256 public totalRevenue;

    // Chainlink CRE integration
    address public creAutomation;  // Address authorized to call CRE functions

    // Subscription tracking
    uint256 public totalSubscribers;
    uint256 public activeSubscribers;

    // =============================================================================
    // EVENTS
    // =============================================================================

    event SubscriptionCreated(
        address indexed subscriber,
        SubscriptionTier tier,
        uint256 expiresAt,
        bytes32 apiKeyHash
    );

    event SubscriptionRenewed(
        address indexed subscriber,
        SubscriptionTier tier,
        uint256 newExpiresAt,
        uint256 amountPaid
    );

    event SubscriptionCancelled(address indexed subscriber);

    event SubscriptionUpgraded(
        address indexed subscriber,
        SubscriptionTier oldTier,
        SubscriptionTier newTier
    );

    event APICallRecorded(address indexed subscriber, uint256 callsUsed);

    event RevenueWithdrawn(address indexed to, address token, uint256 amount);

    event TierConfigUpdated(SubscriptionTier tier, uint256 price, uint256 calls);

    event PaymentTokenUpdated(address token, bool accepted);

    // =============================================================================
    // MODIFIERS
    // =============================================================================

    modifier onlyActiveSubscriber() {
        require(
            subscriptions[msg.sender].status == SubscriptionStatus.ACTIVE,
            "No active subscription"
        );
        require(
            block.timestamp < subscriptions[msg.sender].expiresAt,
            "Subscription expired"
        );
        _;
    }

    modifier onlyCREAutomation() {
        require(
            msg.sender == creAutomation || msg.sender == owner(),
            "Not authorized for CRE operations"
        );
        _;
    }

    // =============================================================================
    // CONSTRUCTOR
    // =============================================================================

    constructor(address _treasury) Ownable() {
        treasuryAddress = _treasury;

        // Initialize tier configurations (prices in 6 decimals for USDC)
        tierConfigs[SubscriptionTier.FREE] = TierConfig({
            priceUSD: 0,
            callsPerMonth: 100,
            ratePerMinute: 10,
            active: true
        });

        tierConfigs[SubscriptionTier.BASIC] = TierConfig({
            priceUSD: 46_000000,  // $46 USD
            callsPerMonth: 10000,
            ratePerMinute: 60,
            active: true
        });

        tierConfigs[SubscriptionTier.PRO] = TierConfig({
            priceUSD: 139_000000,  // $139 USD
            callsPerMonth: 100000,
            ratePerMinute: 300,
            active: true
        });

        tierConfigs[SubscriptionTier.ENTERPRISE] = TierConfig({
            priceUSD: 462_000000,  // $462 USD
            callsPerMonth: 1000000,
            ratePerMinute: 1000,
            active: true
        });
    }

    // =============================================================================
    // SUBSCRIPTION MANAGEMENT
    // =============================================================================

    /**
     * @notice Subscribe to a tier with ERC20 payment
     * @param tier The subscription tier
     * @param token The ERC20 token to pay with
     * @param apiKeyHash Hash of the API key (keccak256 of actual key)
     * @param enableAutoRenew Whether to enable auto-renewal
     */
    function subscribe(
        SubscriptionTier tier,
        address token,
        bytes32 apiKeyHash,
        bool enableAutoRenew
    ) external nonReentrant whenNotPaused {
        require(tierConfigs[tier].active, "Tier not active");
        require(acceptedTokens[token] || tier == SubscriptionTier.FREE, "Token not accepted");
        require(apiKeyToSubscriber[apiKeyHash] == address(0), "API key already registered");

        TierConfig memory config = tierConfigs[tier];

        // Handle payment for non-free tiers
        if (tier != SubscriptionTier.FREE) {
            IERC20(token).safeTransferFrom(msg.sender, address(this), config.priceUSD);
            totalRevenue += config.priceUSD;
        }

        // Create subscription
        uint256 expiresAt = tier == SubscriptionTier.FREE
            ? type(uint256).max  // Free tier never expires
            : block.timestamp + 30 days;

        subscriptions[msg.sender] = Subscription({
            subscriber: msg.sender,
            tier: tier,
            status: SubscriptionStatus.ACTIVE,
            startTime: block.timestamp,
            expiresAt: expiresAt,
            callsPerMonth: config.callsPerMonth,
            callsUsed: 0,
            apiKeyHash: apiKeyHash,
            paymentToken: token,
            amountPaid: config.priceUSD,
            autoRenew: enableAutoRenew
        });

        apiKeyToSubscriber[apiKeyHash] = msg.sender;
        totalSubscribers++;
        activeSubscribers++;

        emit SubscriptionCreated(msg.sender, tier, expiresAt, apiKeyHash);
    }

    /**
     * @notice Renew an existing subscription
     * @param token The ERC20 token to pay with
     */
    function renewSubscription(address token) external nonReentrant whenNotPaused {
        Subscription storage sub = subscriptions[msg.sender];
        require(sub.subscriber != address(0), "No subscription found");
        require(sub.tier != SubscriptionTier.FREE, "Free tier doesn't need renewal");
        require(acceptedTokens[token], "Token not accepted");

        TierConfig memory config = tierConfigs[sub.tier];

        // Process payment
        IERC20(token).safeTransferFrom(msg.sender, address(this), config.priceUSD);
        totalRevenue += config.priceUSD;

        // Extend subscription
        uint256 newExpiry = sub.expiresAt > block.timestamp
            ? sub.expiresAt + 30 days  // Extend from current expiry
            : block.timestamp + 30 days;  // Start fresh if expired

        sub.expiresAt = newExpiry;
        sub.status = SubscriptionStatus.ACTIVE;
        sub.callsUsed = 0;  // Reset monthly calls
        sub.paymentToken = token;
        sub.amountPaid += config.priceUSD;

        emit SubscriptionRenewed(msg.sender, sub.tier, newExpiry, config.priceUSD);
    }

    /**
     * @notice Upgrade subscription tier
     * @param newTier The new subscription tier
     * @param token The ERC20 token to pay the difference
     */
    function upgradeTier(
        SubscriptionTier newTier,
        address token
    ) external nonReentrant whenNotPaused onlyActiveSubscriber {
        Subscription storage sub = subscriptions[msg.sender];
        require(uint256(newTier) > uint256(sub.tier), "Can only upgrade to higher tier");
        require(tierConfigs[newTier].active, "Tier not active");
        require(acceptedTokens[token], "Token not accepted");

        // Calculate prorated price difference
        uint256 oldPrice = tierConfigs[sub.tier].priceUSD;
        uint256 newPrice = tierConfigs[newTier].priceUSD;
        uint256 priceDiff = newPrice - oldPrice;

        // Process payment
        IERC20(token).safeTransferFrom(msg.sender, address(this), priceDiff);
        totalRevenue += priceDiff;

        SubscriptionTier oldTier = sub.tier;
        sub.tier = newTier;
        sub.callsPerMonth = tierConfigs[newTier].callsPerMonth;
        sub.amountPaid += priceDiff;

        emit SubscriptionUpgraded(msg.sender, oldTier, newTier);
    }

    /**
     * @notice Cancel subscription (no refunds)
     */
    function cancelSubscription() external {
        Subscription storage sub = subscriptions[msg.sender];
        require(sub.subscriber != address(0), "No subscription found");

        sub.status = SubscriptionStatus.CANCELLED;
        sub.autoRenew = false;
        activeSubscribers--;

        emit SubscriptionCancelled(msg.sender);
    }

    // =============================================================================
    // ON-CHAIN ACCESS CONTROL
    // =============================================================================

    /**
     * @notice Validate an API key has active subscription
     * @param apiKeyHash Hash of the API key to validate
     * @return valid Whether the API key has an active subscription
     * @return tier The subscription tier
     * @return callsRemaining Number of API calls remaining
     */
    function validateAPIKey(bytes32 apiKeyHash) external view returns (
        bool valid,
        SubscriptionTier tier,
        uint256 callsRemaining
    ) {
        address subscriber = apiKeyToSubscriber[apiKeyHash];
        if (subscriber == address(0)) {
            return (false, SubscriptionTier.FREE, 0);
        }

        Subscription memory sub = subscriptions[subscriber];

        if (sub.status != SubscriptionStatus.ACTIVE) {
            return (false, sub.tier, 0);
        }

        if (block.timestamp >= sub.expiresAt) {
            return (false, sub.tier, 0);
        }

        uint256 remaining = sub.callsPerMonth > sub.callsUsed
            ? sub.callsPerMonth - sub.callsUsed
            : 0;

        return (true, sub.tier, remaining);
    }

    /**
     * @notice Record an API call usage (called by API server)
     * @param apiKeyHash Hash of the API key
     */
    function recordAPICall(bytes32 apiKeyHash) external onlyCREAutomation {
        address subscriber = apiKeyToSubscriber[apiKeyHash];
        require(subscriber != address(0), "Invalid API key");

        Subscription storage sub = subscriptions[subscriber];
        require(sub.status == SubscriptionStatus.ACTIVE, "Subscription not active");
        require(block.timestamp < sub.expiresAt, "Subscription expired");
        require(sub.callsUsed < sub.callsPerMonth, "Monthly call limit reached");

        sub.callsUsed++;

        emit APICallRecorded(subscriber, sub.callsUsed);
    }

    // =============================================================================
    // CRE AUTOMATION FUNCTIONS
    // =============================================================================

    /**
     * @notice Process auto-renewals (called by CRE CRON workflow)
     * @param subscribers Array of subscriber addresses to process
     */
    function processAutoRenewals(address[] calldata subscribers) external onlyCREAutomation {
        for (uint256 i = 0; i < subscribers.length; i++) {
            Subscription storage sub = subscriptions[subscribers[i]];

            // Skip if not eligible for auto-renewal
            if (!sub.autoRenew) continue;
            if (sub.status != SubscriptionStatus.ACTIVE) continue;
            if (block.timestamp < sub.expiresAt - 3 days) continue;  // Only renew within 3 days of expiry

            TierConfig memory config = tierConfigs[sub.tier];
            address token = sub.paymentToken;

            // Check if subscriber has approved enough tokens
            uint256 allowance = IERC20(token).allowance(subscribers[i], address(this));
            uint256 balance = IERC20(token).balanceOf(subscribers[i]);

            if (allowance >= config.priceUSD && balance >= config.priceUSD) {
                // Process auto-renewal
                IERC20(token).safeTransferFrom(subscribers[i], address(this), config.priceUSD);
                totalRevenue += config.priceUSD;

                sub.expiresAt += 30 days;
                sub.callsUsed = 0;
                sub.amountPaid += config.priceUSD;

                emit SubscriptionRenewed(subscribers[i], sub.tier, sub.expiresAt, config.priceUSD);
            } else {
                // Mark as expired if can't auto-renew
                if (block.timestamp >= sub.expiresAt) {
                    sub.status = SubscriptionStatus.EXPIRED;
                    activeSubscribers--;
                }
            }
        }
    }

    /**
     * @notice Reset monthly call counts (called by CRE at month start)
     * @param subscribers Array of subscriber addresses to reset
     */
    function resetMonthlyCalls(address[] calldata subscribers) external onlyCREAutomation {
        for (uint256 i = 0; i < subscribers.length; i++) {
            if (subscriptions[subscribers[i]].status == SubscriptionStatus.ACTIVE) {
                subscriptions[subscribers[i]].callsUsed = 0;
            }
        }
    }

    // =============================================================================
    // ADMIN FUNCTIONS
    // =============================================================================

    /**
     * @notice Add or remove accepted payment token
     */
    function setPaymentToken(address token, bool accepted) external onlyOwner {
        acceptedTokens[token] = accepted;
        if (accepted) {
            tokenList.push(token);
        }
        emit PaymentTokenUpdated(token, accepted);
    }

    /**
     * @notice Update tier configuration
     */
    function setTierConfig(
        SubscriptionTier tier,
        uint256 priceUSD,
        uint256 callsPerMonth,
        uint256 ratePerMinute,
        bool active
    ) external onlyOwner {
        tierConfigs[tier] = TierConfig({
            priceUSD: priceUSD,
            callsPerMonth: callsPerMonth,
            ratePerMinute: ratePerMinute,
            active: active
        });
        emit TierConfigUpdated(tier, priceUSD, callsPerMonth);
    }

    /**
     * @notice Set CRE automation address
     */
    function setCREAutomation(address _creAutomation) external onlyOwner {
        creAutomation = _creAutomation;
    }

    /**
     * @notice Set treasury address (Fedimint bridge)
     */
    function setTreasury(address _treasury) external onlyOwner {
        treasuryAddress = _treasury;
    }

    /**
     * @notice Withdraw revenue to treasury
     */
    function withdrawRevenue(address token) external onlyOwner nonReentrant {
        uint256 balance = IERC20(token).balanceOf(address(this));
        require(balance > 0, "No balance to withdraw");

        IERC20(token).safeTransfer(treasuryAddress, balance);

        emit RevenueWithdrawn(treasuryAddress, token, balance);
    }

    /**
     * @notice Emergency pause
     */
    function pause() external onlyOwner {
        _pause();
    }

    /**
     * @notice Unpause
     */
    function unpause() external onlyOwner {
        _unpause();
    }

    // =============================================================================
    // VIEW FUNCTIONS
    // =============================================================================

    function getSubscription(address subscriber) external view returns (Subscription memory) {
        return subscriptions[subscriber];
    }

    function getTierConfig(SubscriptionTier tier) external view returns (TierConfig memory) {
        return tierConfigs[tier];
    }

    function getAcceptedTokens() external view returns (address[] memory) {
        return tokenList;
    }

    function isSubscriptionActive(address subscriber) external view returns (bool) {
        Subscription memory sub = subscriptions[subscriber];
        return sub.status == SubscriptionStatus.ACTIVE && block.timestamp < sub.expiresAt;
    }
}
