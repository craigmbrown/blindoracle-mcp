/**
 * Chainlink CRE Subscription Management Workflow
 * ===============================================
 *
 * Handles:
 * - New subscription processing via HTTP trigger
 * - Auto-renewal via CRON trigger (daily at midnight)
 * - Monthly call count reset (1st of each month)
 * - On-chain access control validation
 * - KV store for subscription state caching
 *
 * Contract Integration:
 * - Calls OracleSubscription.sol for payment processing
 * - Updates subscription status on-chain
 * - Records API usage for billing
 *
 * @requirement REQ-CRE-001 - Automated subscription management
 * @requirement REQ-CRE-002 - On-chain payment verification
 * @requirement REQ-CRE-003 - Auto-renewal processing
 */

import {
  cre,
  Runner,
  type Runtime,
  type CronPayload,
  type HTTPPayload,
} from "@chainlink/cre-sdk";

// =============================================================================
// CONFIGURATION
// =============================================================================

interface Config {
  // Contract addresses
  subscriptionContract: string;
  usdcToken: string;
  usdtToken: string;
  daiToken: string;
  linkToken: string;

  // Network configuration
  network: "ethereum" | "sepolia" | "base" | "arbitrum";
  rpcUrl: string;

  // CRON schedules
  autoRenewalSchedule: string; // Daily at midnight: "0 0 * * *"
  monthlyResetSchedule: string; // 1st of month: "0 0 1 * *"

  // API configuration
  apiBaseUrl: string;
}

// Subscription tiers (must match contract)
enum SubscriptionTier {
  FREE = 0,
  BASIC = 1,
  PRO = 2,
  ENTERPRISE = 3,
}

// Tier pricing in USD (6 decimals)
const TIER_PRICES: Record<SubscriptionTier, bigint> = {
  [SubscriptionTier.FREE]: 0n,
  [SubscriptionTier.BASIC]: 46_000000n,
  [SubscriptionTier.PRO]: 139_000000n,
  [SubscriptionTier.ENTERPRISE]: 462_000000n,
};

// Contract ABIs (partial for used functions)
const SUBSCRIPTION_ABI = [
  {
    name: "subscribe",
    type: "function",
    inputs: [
      { name: "tier", type: "uint8" },
      { name: "token", type: "address" },
      { name: "apiKeyHash", type: "bytes32" },
      { name: "enableAutoRenew", type: "bool" },
    ],
    outputs: [],
  },
  {
    name: "processAutoRenewals",
    type: "function",
    inputs: [{ name: "subscribers", type: "address[]" }],
    outputs: [],
  },
  {
    name: "resetMonthlyCalls",
    type: "function",
    inputs: [{ name: "subscribers", type: "address[]" }],
    outputs: [],
  },
  {
    name: "validateAPIKey",
    type: "function",
    inputs: [{ name: "apiKeyHash", type: "bytes32" }],
    outputs: [
      { name: "valid", type: "bool" },
      { name: "tier", type: "uint8" },
      { name: "callsRemaining", type: "uint256" },
    ],
    stateMutability: "view",
  },
  {
    name: "recordAPICall",
    type: "function",
    inputs: [{ name: "apiKeyHash", type: "bytes32" }],
    outputs: [],
  },
  {
    name: "getSubscription",
    type: "function",
    inputs: [{ name: "subscriber", type: "address" }],
    outputs: [
      {
        name: "",
        type: "tuple",
        components: [
          { name: "subscriber", type: "address" },
          { name: "tier", type: "uint8" },
          { name: "status", type: "uint8" },
          { name: "startTime", type: "uint256" },
          { name: "expiresAt", type: "uint256" },
          { name: "callsPerMonth", type: "uint256" },
          { name: "callsUsed", type: "uint256" },
          { name: "apiKeyHash", type: "bytes32" },
          { name: "paymentToken", type: "address" },
          { name: "amountPaid", type: "uint256" },
          { name: "autoRenew", type: "bool" },
        ],
      },
    ],
    stateMutability: "view",
  },
];

const ERC20_ABI = [
  {
    name: "allowance",
    type: "function",
    inputs: [
      { name: "owner", type: "address" },
      { name: "spender", type: "address" },
    ],
    outputs: [{ name: "", type: "uint256" }],
    stateMutability: "view",
  },
  {
    name: "balanceOf",
    type: "function",
    inputs: [{ name: "account", type: "address" }],
    outputs: [{ name: "", type: "uint256" }],
    stateMutability: "view",
  },
];

// =============================================================================
// CAPABILITIES
// =============================================================================

const evmCapability = new cre.capabilities.EVMCapability();
const kvStore = new cre.capabilities.KVCapability();
const cronCapability = new cre.capabilities.CronCapability();
const httpCapability = new cre.capabilities.HTTPCapability();

// =============================================================================
// HTTP HANDLERS
// =============================================================================

interface SubscribeRequest {
  customerAddress: string;
  tier: SubscriptionTier;
  paymentToken: string;
  apiKey: string; // Plain text API key (will be hashed)
  autoRenew: boolean;
}

interface ValidateRequest {
  apiKey: string;
}

interface RecordUsageRequest {
  apiKey: string;
}

/**
 * Handle new subscription requests
 */
async function handleSubscribe(
  runtime: Runtime<Config>,
  payload: HTTPPayload
): Promise<{ success: boolean; message: string; txHash?: string }> {
  const config = runtime.config;
  const request = payload.body as SubscribeRequest;

  runtime.log(`Processing subscription for ${request.customerAddress}`);

  try {
    // Hash the API key for on-chain storage
    const apiKeyHash = evmCapability.keccak256(request.apiKey);

    // Verify token allowance before attempting subscription
    const allowance = await evmCapability.readContract({
      network: config.network,
      rpcUrl: config.rpcUrl,
      contractAddress: request.paymentToken,
      abi: ERC20_ABI,
      functionName: "allowance",
      params: [request.customerAddress, config.subscriptionContract],
    });

    const requiredAmount = TIER_PRICES[request.tier];

    if (BigInt(allowance as string) < requiredAmount) {
      return {
        success: false,
        message: `Insufficient allowance. Required: ${requiredAmount}, Current: ${allowance}`,
      };
    }

    // Call contract to create subscription
    const txHash = await evmCapability.writeContract({
      network: config.network,
      rpcUrl: config.rpcUrl,
      contractAddress: config.subscriptionContract,
      abi: SUBSCRIPTION_ABI,
      functionName: "subscribe",
      params: [request.tier, request.paymentToken, apiKeyHash, request.autoRenew],
    });

    // Cache subscription in KV store for quick lookups
    await kvStore.set(`sub:${request.customerAddress}`, {
      tier: request.tier,
      apiKeyHash,
      autoRenew: request.autoRenew,
      createdAt: Date.now(),
      expiresAt: Date.now() + 30 * 24 * 60 * 60 * 1000, // 30 days
    });

    // Add to active subscribers list
    const activeList = (await kvStore.get("active_subscribers")) || [];
    activeList.push(request.customerAddress);
    await kvStore.set("active_subscribers", activeList);

    runtime.log(`Subscription created. TxHash: ${txHash}`);

    return {
      success: true,
      message: "Subscription created successfully",
      txHash: txHash as string,
    };
  } catch (error) {
    runtime.log(`Subscription failed: ${error}`);
    return {
      success: false,
      message: `Subscription failed: ${error}`,
    };
  }
}

/**
 * Validate API key on-chain
 */
async function handleValidate(
  runtime: Runtime<Config>,
  payload: HTTPPayload
): Promise<{ valid: boolean; tier: number; callsRemaining: number }> {
  const config = runtime.config;
  const request = payload.body as ValidateRequest;

  try {
    const apiKeyHash = evmCapability.keccak256(request.apiKey);

    const result = await evmCapability.readContract({
      network: config.network,
      rpcUrl: config.rpcUrl,
      contractAddress: config.subscriptionContract,
      abi: SUBSCRIPTION_ABI,
      functionName: "validateAPIKey",
      params: [apiKeyHash],
    });

    const [valid, tier, callsRemaining] = result as [boolean, number, bigint];

    return {
      valid,
      tier,
      callsRemaining: Number(callsRemaining),
    };
  } catch (error) {
    runtime.log(`Validation failed: ${error}`);
    return {
      valid: false,
      tier: 0,
      callsRemaining: 0,
    };
  }
}

/**
 * Record API usage on-chain
 */
async function handleRecordUsage(
  runtime: Runtime<Config>,
  payload: HTTPPayload
): Promise<{ success: boolean; txHash?: string }> {
  const config = runtime.config;
  const request = payload.body as RecordUsageRequest;

  try {
    const apiKeyHash = evmCapability.keccak256(request.apiKey);

    const txHash = await evmCapability.writeContract({
      network: config.network,
      rpcUrl: config.rpcUrl,
      contractAddress: config.subscriptionContract,
      abi: SUBSCRIPTION_ABI,
      functionName: "recordAPICall",
      params: [apiKeyHash],
    });

    return {
      success: true,
      txHash: txHash as string,
    };
  } catch (error) {
    runtime.log(`Usage recording failed: ${error}`);
    return {
      success: false,
    };
  }
}

// =============================================================================
// CRON HANDLERS
// =============================================================================

/**
 * Process auto-renewals daily at midnight
 */
async function handleAutoRenewal(
  runtime: Runtime<Config>,
  _payload: CronPayload
): Promise<void> {
  const config = runtime.config;

  runtime.log("Starting auto-renewal processing...");

  try {
    // Get list of active subscribers from KV store
    const activeSubscribers = (await kvStore.get("active_subscribers")) || [];

    if (activeSubscribers.length === 0) {
      runtime.log("No active subscribers to process");
      return;
    }

    // Filter subscribers expiring within 3 days
    const expiringSubscribers: string[] = [];
    const now = Date.now();
    const threeDaysFromNow = now + 3 * 24 * 60 * 60 * 1000;

    for (const address of activeSubscribers) {
      const subData = await kvStore.get(`sub:${address}`);
      if (subData && subData.autoRenew && subData.expiresAt <= threeDaysFromNow) {
        expiringSubscribers.push(address);
      }
    }

    if (expiringSubscribers.length === 0) {
      runtime.log("No subscriptions expiring soon");
      return;
    }

    runtime.log(`Processing ${expiringSubscribers.length} auto-renewals`);

    // Call contract to process renewals in batches of 50
    const batchSize = 50;
    for (let i = 0; i < expiringSubscribers.length; i += batchSize) {
      const batch = expiringSubscribers.slice(i, i + batchSize);

      const txHash = await evmCapability.writeContract({
        network: config.network,
        rpcUrl: config.rpcUrl,
        contractAddress: config.subscriptionContract,
        abi: SUBSCRIPTION_ABI,
        functionName: "processAutoRenewals",
        params: [batch],
      });

      runtime.log(`Batch ${i / batchSize + 1} processed. TxHash: ${txHash}`);

      // Update KV store for renewed subscriptions
      for (const address of batch) {
        const subData = await kvStore.get(`sub:${address}`);
        if (subData) {
          subData.expiresAt = Date.now() + 30 * 24 * 60 * 60 * 1000;
          await kvStore.set(`sub:${address}`, subData);
        }
      }
    }

    runtime.log("Auto-renewal processing complete");
  } catch (error) {
    runtime.log(`Auto-renewal failed: ${error}`);
  }
}

/**
 * Reset monthly call counts on the 1st of each month
 */
async function handleMonthlyReset(
  runtime: Runtime<Config>,
  _payload: CronPayload
): Promise<void> {
  const config = runtime.config;

  runtime.log("Starting monthly call count reset...");

  try {
    const activeSubscribers = (await kvStore.get("active_subscribers")) || [];

    if (activeSubscribers.length === 0) {
      runtime.log("No subscribers to reset");
      return;
    }

    // Process in batches of 100
    const batchSize = 100;
    for (let i = 0; i < activeSubscribers.length; i += batchSize) {
      const batch = activeSubscribers.slice(i, i + batchSize);

      const txHash = await evmCapability.writeContract({
        network: config.network,
        rpcUrl: config.rpcUrl,
        contractAddress: config.subscriptionContract,
        abi: SUBSCRIPTION_ABI,
        functionName: "resetMonthlyCalls",
        params: [batch],
      });

      runtime.log(`Reset batch ${i / batchSize + 1}. TxHash: ${txHash}`);
    }

    runtime.log("Monthly reset complete");
  } catch (error) {
    runtime.log(`Monthly reset failed: ${error}`);
  }
}

// =============================================================================
// WORKFLOW INITIALIZATION
// =============================================================================

function initWorkflow(config: Config) {
  return [
    // HTTP endpoint for new subscriptions
    cre.handler(
      httpCapability.trigger({ path: "/subscribe", method: "POST" }),
      handleSubscribe
    ),

    // HTTP endpoint for API key validation
    cre.handler(
      httpCapability.trigger({ path: "/validate", method: "POST" }),
      handleValidate
    ),

    // HTTP endpoint for usage recording
    cre.handler(
      httpCapability.trigger({ path: "/record-usage", method: "POST" }),
      handleRecordUsage
    ),

    // CRON trigger for auto-renewals (daily at midnight)
    cre.handler(
      cronCapability.trigger({ schedule: config.autoRenewalSchedule }),
      handleAutoRenewal
    ),

    // CRON trigger for monthly call reset (1st of each month)
    cre.handler(
      cronCapability.trigger({ schedule: config.monthlyResetSchedule }),
      handleMonthlyReset
    ),
  ];
}

// =============================================================================
// MAIN ENTRY POINT
// =============================================================================

export async function main() {
  const runner = await Runner.newRunner<Config>();
  await runner.run(initWorkflow);
}

main();
