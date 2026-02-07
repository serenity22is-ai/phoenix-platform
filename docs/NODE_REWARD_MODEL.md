# Phoenix Node Reward Model (Internal Documentation)

## Overview

The Phoenix network uses a dual-value node system where different node types contribute different value to the ecosystem and are rewarded accordingly.

---

## Node Types

### Mobile Nodes
- **Platform**: iOS/Android apps running in background
- **Typical Uptime**: ~90% (phone always on, app permissions granted)
- **Data Value**: HIGH
  - Browsing activity
  - App usage patterns
  - Location data (with consent)
  - Search patterns
- **Primary Reward Source**: Data marketplace revenue

### Desktop Nodes
- **Platform**: macOS/Windows/Linux desktop applications
- **Typical Uptime**: Variable (depends on user habits)
- **Data Value**: HIGH
  - Browsing activity
  - Search patterns
  - Shopping behavior
- **Primary Reward Source**: Data marketplace revenue

### Dedicated Server Nodes
- **Platform**: Always-on hardware (Raspberry Pi, home servers, NUCs)
- **Typical Uptime**: 100% (never powers off)
- **Data Value**: LOW/NONE (no user activity, just infrastructure)
- **Primary Reward Source**: Uptime/infrastructure rewards
- **Special Value**: Stable residential IPs for premium proxy operations

---

## Node Value Matrix

| Node Type | Uptime | Data Value | Proxy Value | Reward Type |
|-----------|--------|------------|-------------|-------------|
| Mobile | ~90% | HIGH | Standard | Data rewards |
| Desktop | Variable | HIGH | Standard | Data rewards |
| Dedicated | 100% | NONE | Premium (stable IP) | Uptime rewards |

---

## Tier System

### Phase 1 (Launch)
- **All nodes**: Bronze tier
- **Reward distribution**: Even split across all active nodes
- **Revenue source**: Proxy B2B sales
- **Simplicity**: No uptime tracking, no data rewards yet

### Phase 2 (Post-CitizenSERP)
- **Tier qualification**: Based on node uptime
  - Bronze: < 50% uptime
  - Silver: 50-79% uptime
  - Gold: 80-94% uptime
  - Platinum: 95%+ uptime (or dedicated server verified)
- **Uptime rewards**: Higher tier = larger share of proxy revenue pool

### Phase 3 (Data Marketplace)
- **Data rewards**: Mobile/desktop nodes earn from browsing data sales
- **Uptime rewards**: Dedicated servers continue earning infrastructure rewards
- **Separate pools**: Data revenue and proxy revenue distributed independently

### Phase 4 (Public Model)
- **Open marketing**: "Earn passive income with always-on hardware"
- **Target audience**: Crypto miners, homelabbers, tech enthusiasts
- **Clear value prop**: Dedicated servers = uptime rewards only, no data

---

## Reward Distribution Logic

### Phase 1 (Simple Even Split)
```
total_payout = proxy_revenue * (node_payout_pct / 100)
per_node_payout = total_payout / active_node_count
```

### Phase 2+ (Weighted by Tier)
```
tier_weights = {
    'bronze': 1,
    'silver': 1.5,
    'gold': 2,
    'platinum': 3
}

total_weight = sum(tier_weights[node.tier] for node in active_nodes)
node_payout = (tier_weights[node.tier] / total_weight) * total_payout
```

### Phase 3+ (Dual Revenue Streams)
```
# Uptime rewards (all nodes)
uptime_pool = proxy_revenue * node_payout_pct
distribute_by_tier_weight(uptime_pool, all_active_nodes)

# Data rewards (mobile/desktop only)
data_pool = data_marketplace_revenue * data_payout_pct
distribute_by_data_contribution(data_pool, data_generating_nodes)
```

---

## Dedicated Server Onboarding (Future)

### Verification Methods
1. **Uptime threshold**: Auto-promote to Platinum after 30 days of 99%+ uptime
2. **Self-declaration**: User marks node as "dedicated" during setup
3. **Admin approval**: Manual verification for early adopters

### Install Options
- Headless Linux install script
- Docker container
- Auto-start on boot configuration
- Raspberry Pi optimized image

---

## CitizenSERP Integration

Dedicated server nodes with stable residential IPs are ideal for:
- SERP crawling (search engine results)
- Price monitoring
- Market research automation

These nodes don't generate user activity data but provide consistent, high-quality proxy infrastructure for the network's data collection needs.

---

## Key Principles

1. **Honest value exchange**: Each node type knows what they're contributing and what they earn
2. **No bait and switch**: Dedicated servers marketed for uptime rewards, not data rewards
3. **Phased complexity**: Start simple (even split), add sophistication as network grows
4. **Separate pools**: Data rewards and uptime rewards are distinct revenue streams

---

## Payment Infrastructure

- **Currency**: RLUSD (Ripple USD stablecoin)
- **Off-ramp**: Moonpay integration for fiat conversion
- **Frequency**: TBD (monthly, weekly, or threshold-based)

---

*Last updated: Build #96*
*This document is internal only - do not expose to users until Phase 4*
