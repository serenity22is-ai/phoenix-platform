#!/usr/bin/env python3
"""Build #168: Remove CitizenSERP/P2P/Node models from models.py"""

import re

MODELS_PATH = '/Users/adramainjest/flightfinder2/models.py'

# Classes to REMOVE (CitizenSERP/P2P/Node infrastructure)
REMOVE_CLASSES = {
    'HelperProfile',
    'P2PTransaction',
    'P2PEscrow',
    'Dispute',
    'DisputeMessage',
    'NodeSession',
    'NodePayoutEpoch',
    'NodePayout',
    'NodeDataExtraction',
    'AdIntelligenceRecord',
    'BrowsingEvent',
    'DataQualityFeedback',
    'ProxySession',
    'BrowseSession',
    'PrivateMarketDeal',
    'SERPAPIQuery',
    'SERPAPIUsageSummary',
    'DataProduct',
    'DataSubscription',
    'DataExport',
    'DataWebhook',
    'DataUsageRecord',
    'NodeConsentProfile',
    'NodeReferral',
    'NodeTierHistory',
    'FleetAccount',
    'RevenueAllocation',
    'CryptoConversion',
    'PricingZone',
    'PriceObservation',
    'NodeLocationHistory',
    'HarvestExecution',
    'StandingOrder',
    'HarvestBudget',
    'PaymentZoneRule',
    'PaymentInteropGroup',
    'RampProvider',
    'VirtualCardTransaction',
    'UserRampPreference',
    'ZoneEconomicsSnapshot',
}

with open(MODELS_PATH, 'r') as f:
    lines = f.readlines()

# Step 1: Find class boundaries
class_ranges = []  # (start_line_idx, end_line_idx, class_name)
class_pattern = re.compile(r'^class (\w+)\(')

for i, line in enumerate(lines):
    m = class_pattern.match(line)
    if m:
        class_ranges.append((i, m.group(1)))

# Determine end of each class (line before next class or section comment block)
class_blocks = []
for idx, (start, name) in enumerate(class_ranges):
    if idx + 1 < len(class_ranges):
        end = class_ranges[idx + 1][0]
    else:
        end = len(lines)
    class_blocks.append((start, end, name))

# Step 2: For each class to remove, also remove preceding comment/separator blocks
# Look backwards from class start to find section headers like "# ---" or "# ==="
def find_section_start(lines, class_start):
    """Find the start of a section header block preceding a class."""
    i = class_start - 1
    # Skip blank lines
    while i >= 0 and lines[i].strip() == '':
        i -= 1
    # If we hit a comment line that's a separator, keep going backwards
    if i >= 0 and (lines[i].strip().startswith('# ---') or lines[i].strip().startswith('# ===')):
        # We're in a section comment block, go up to find its start
        while i >= 0 and (lines[i].strip().startswith('#') or lines[i].strip() == ''):
            i -= 1
        return i + 1
    return class_start

# Step 3: Build removal ranges
remove_ranges = set()
for start, end, name in class_blocks:
    if name in REMOVE_CLASSES:
        section_start = find_section_start(lines, start)
        for j in range(section_start, end):
            remove_ranges.add(j)

# Step 4: Write filtered output
output_lines = []
for i, line in enumerate(lines):
    if i not in remove_ranges:
        output_lines.append(line)

# Step 5: Clean up excessive blank lines (3+ consecutive → 2)
final_lines = []
blank_count = 0
for line in output_lines:
    if line.strip() == '':
        blank_count += 1
        if blank_count <= 2:
            final_lines.append(line)
    else:
        blank_count = 0
        final_lines.append(line)

with open(MODELS_PATH, 'w') as f:
    f.writelines(final_lines)

# Report
original_count = len(lines)
new_count = len(final_lines)
removed_count = original_count - new_count
print(f"Original: {original_count} lines")
print(f"New: {new_count} lines")
print(f"Removed: {removed_count} lines")
print(f"Classes removed: {len(REMOVE_CLASSES)}")

# Verify remaining classes
remaining = []
for line in final_lines:
    m = class_pattern.match(line)
    if m:
        remaining.append(m.group(1))
print(f"\nRemaining classes ({len(remaining)}):")
for c in remaining:
    print(f"  {c}")
