// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/utils/introspection/IERC165.sol";

/**
 * @title IReceiver
 * @notice Chainlink CRE Receiver Interface
 * @dev Contracts implementing this interface can receive reports from CRE workflows
 *
 * The CRE workflow calls onReport() with:
 * - metadata: Contains workflow owner address (20 bytes) and workflow name (10 bytes)
 * - report: ABI-encoded data specific to the workflow (e.g., market outcome)
 *
 * @custom:security-contact security@example.com
 */
interface IReceiver is IERC165 {
    /**
     * @notice Receive a report from a CRE workflow
     * @param metadata Encoded workflow metadata (owner address + workflow name)
     * @param report ABI-encoded report data from the workflow
     *
     * Metadata format (32 bytes total):
     * - bytes 0-19: Workflow owner address (address, 20 bytes)
     * - bytes 20-29: Workflow name (bytes10, 10 bytes)
     * - bytes 30-31: Padding (2 bytes)
     *
     * Example metadata decoding:
     * ```solidity
     * (address workflowOwner, bytes10 workflowName) = _decodeMetadata(metadata);
     * ```
     */
    function onReport(bytes calldata metadata, bytes calldata report) external;
}
