"""
Strategy Learner Engine — Build #73
Three-phase learning system: Record, Aggregate, Apply
Plus competitive comparison (MystesAI vs BYOAI).
"""

import json
import logging
import secrets
from datetime import datetime, timedelta
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class StrategyLearner:
    """
    Core strategy learning engine that observes searches, aggregates patterns,
    and applies learned strategies to enhance future searches.
    """

    # ------------------------------------------------------------------ #
    #  Phase 1: Record                                                    #
    # ------------------------------------------------------------------ #

    def record_observation(
        self, source_type, provider_key, query_category,
        query_params, results, response_time_ms=None,
    ):
        """Persist a StrategyObservation for every search that passes through."""
        try:
            from models import StrategyObservation, db

            observation = StrategyObservation(
                observation_id=f"obs_{secrets.token_hex(8)}",
                source_type=source_type,
                provider_key=provider_key or "",
                query_category=query_category or "general",
                query_structure=self._extract_query_structure(query_params),
                source_sites=self._extract_source_sites(results),
                strategies_detected=self._detect_strategies(query_params, results),
                result_count=self._count_results(results),
                result_quality_score=self._score_result_quality(results),
                markets_searched=self._extract_markets(query_params, results),
                response_time_ms=response_time_ms,
                created_at=datetime.utcnow(),
            )
            db.session.add(observation)
            db.session.commit()
            logger.debug("Recorded observation %s", observation.observation_id)
        except Exception as exc:
            logger.warning("Failed to record observation: %s", exc)
            try:
                from models import db
                db.session.rollback()
            except Exception:
                pass

    # -- helpers -------------------------------------------------------- #

    def _extract_query_structure(self, query_params):
        """Anonymise a query into a structural pattern (JSON string)."""
        if not query_params or not isinstance(query_params, dict):
            return json.dumps({"type": "unknown"})

        structure = {}

        # Flight queries
        if any(k in query_params for k in ("origin", "destination", "departure_date")):
            structure["type"] = "flight"
            structure["origin"] = "IATA" if query_params.get("origin") else None
            structure["dest"] = "IATA" if query_params.get("destination") else None
            structure["date_range"] = self._bucket_date_range(query_params)
            structure["flexibility"] = (
                "flexible" if query_params.get("flexible_dates") else "exact"
            )
            pax = query_params.get("passengers", query_params.get("adults", 1))
            try:
                pax = int(pax)
            except (TypeError, ValueError):
                pax = 1
            structure["passengers"] = "1" if pax <= 1 else "2" if pax == 2 else "3+"

        # Hotel queries
        elif any(k in query_params for k in ("checkin", "checkout", "hotel")):
            structure["type"] = "hotel"
            structure["destination_type"] = (
                "city" if query_params.get("city") else "region"
            )
            structure["checkin_range"] = self._bucket_date_range(query_params, key="checkin")
            nights = 1
            try:
                ci = query_params.get("checkin")
                co = query_params.get("checkout")
                if ci and co:
                    nights = max(
                        1,
                        (datetime.fromisoformat(str(co)) - datetime.fromisoformat(str(ci))).days,
                    )
            except Exception:
                pass
            structure["nights"] = (
                "1-3" if nights <= 3 else "4-7" if nights <= 7 else "8+"
            )

        # General / SERP
        else:
            query_text = query_params.get("query", query_params.get("q", ""))
            length = len(str(query_text).split())
            structure["type"] = "general"
            structure["query_length"] = (
                "short" if length <= 3 else "medium" if length <= 7 else "long"
            )
            structure["has_location"] = any(
                k in query_params for k in ("location", "city", "country", "market")
            )
            structure["has_date"] = any(
                k in query_params for k in ("date", "departure_date", "checkin")
            )
            qt = str(query_text).lower()
            if any(w in qt for w in ("buy", "book", "price", "cheap", "deal")):
                structure["query_type"] = "transactional"
            elif any(w in qt for w in ("how", "what", "why", "guide", "best")):
                structure["query_type"] = "informational"
            else:
                structure["query_type"] = "navigational"

        return json.dumps(structure)

    def _bucket_date_range(self, params, key="departure_date"):
        """Return a human-readable date-range bucket."""
        raw = params.get(key) or params.get("date")
        if not raw:
            return "unknown"
        try:
            target = datetime.fromisoformat(str(raw))
            delta = (target - datetime.utcnow()).days
            if delta < 0:
                return "past"
            if delta <= 14:
                return "1-2_weeks"
            if delta <= 28:
                return "2-4_weeks"
            if delta <= 60:
                return "1-2_months"
            return "2-3_months"
        except Exception:
            return "unknown"

    def _extract_source_sites(self, results):
        """Recursively pull unique domains from results (JSON string)."""
        domains = set()
        self._walk_for_urls(results, domains)
        return json.dumps(sorted(domains))

    def _walk_for_urls(self, obj, domains):
        url_keys = {"booking_url", "url", "source", "website", "link", "href"}
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in url_keys and isinstance(v, str) and v.startswith("http"):
                    try:
                        domains.add(urlparse(v).netloc)
                    except Exception:
                        pass
                else:
                    self._walk_for_urls(v, domains)
        elif isinstance(obj, list):
            for item in obj:
                self._walk_for_urls(item, domains)

    def _detect_strategies(self, query_params, results):
        """Detect which strategies were used / present in results."""
        strategies = []
        params = query_params if isinstance(query_params, dict) else {}
        flat_results = results if isinstance(results, list) else (
            results.get("results", []) if isinstance(results, dict) else []
        )

        # multi_market
        markets = set()
        for r in (flat_results if isinstance(flat_results, list) else []):
            if isinstance(r, dict):
                m = r.get("market") or r.get("country") or r.get("pos")
                if m:
                    markets.add(str(m).upper())
        strategies.append({
            "name": "multi_market",
            "detected": len(markets) > 1,
            "details": f"{len(markets)} markets" if markets else "none",
        })

        # date_flexibility
        flex = bool(
            params.get("flexible_dates")
            or params.get("date_range")
            or params.get("flexible")
        )
        strategies.append({
            "name": "date_flexibility",
            "detected": flex,
            "details": "flexible" if flex else "exact",
        })

        # airline_specific
        airline = bool(params.get("airline") or params.get("carrier"))
        strategies.append({
            "name": "airline_specific",
            "detected": airline,
            "details": params.get("airline", params.get("carrier", "none")),
        })

        # price_comparison
        prices = []
        for r in (flat_results if isinstance(flat_results, list) else []):
            if isinstance(r, dict):
                p = r.get("price") or r.get("total_price") or r.get("amount")
                if p is not None:
                    try:
                        prices.append(float(p))
                    except (TypeError, ValueError):
                        pass
        strategies.append({
            "name": "price_comparison",
            "detected": len(prices) > 1,
            "details": f"{len(prices)} prices" if prices else "none",
        })

        # proxy_market_selection
        proxy_markets = {"PL", "ES", "UK", "GB", "IN", "BR", "MX", "TR", "RO"}
        used_proxy = markets & proxy_markets
        strategies.append({
            "name": "proxy_market_selection",
            "detected": bool(used_proxy),
            "details": ",".join(sorted(used_proxy)) if used_proxy else "none",
        })

        # booking_class_optimization
        raw_str = json.dumps(results) if results else ""
        class_terms = {"business", "economy", "premium", "first class", "cabin"}
        found_classes = [t for t in class_terms if t in raw_str.lower()]
        strategies.append({
            "name": "booking_class_optimization",
            "detected": bool(found_classes),
            "details": ",".join(found_classes) if found_classes else "none",
        })

        return json.dumps(strategies)

    def _score_result_quality(self, results):
        """Score result quality 0-100."""
        if not results:
            return 0.0

        flat = results if isinstance(results, list) else (
            results.get("results", []) if isinstance(results, dict) else []
        )
        if not isinstance(flat, list):
            flat = []

        # result_count component (30 pts)
        count = len(flat)
        count_score = min(count / 10.0, 1.0) * 30

        # price_data component (25 pts)
        has_price = False
        for r in flat:
            if isinstance(r, dict) and any(
                r.get(k) is not None for k in ("price", "total_price", "amount", "cost")
            ):
                has_price = True
                break
        price_score = 25.0 if has_price else 0.0

        # savings_found component (25 pts)
        has_savings = False
        raw = json.dumps(results).lower() if results else ""
        if any(w in raw for w in ("saving", "discount", "cheaper", "deal")):
            has_savings = True
        for r in flat:
            if isinstance(r, dict) and any(
                r.get(k) is not None for k in ("savings", "discount", "savings_pct")
            ):
                has_savings = True
                break
        savings_score = 25.0 if has_savings else 0.0

        # market_diversity component (10 pts)
        uniq_markets = set()
        for r in flat:
            if isinstance(r, dict):
                m = r.get("market") or r.get("country") or r.get("pos")
                if m:
                    uniq_markets.add(str(m))
        market_score = min(len(uniq_markets) / 5.0, 1.0) * 10

        # data_completeness component (10 pts)
        expected = {"price", "url", "source", "market", "airline", "date"}
        present = set()
        for r in flat:
            if isinstance(r, dict):
                present.update(k for k in expected if r.get(k) is not None)
        completeness_score = (len(present) / max(len(expected), 1)) * 10

        return round(
            count_score + price_score + savings_score + market_score + completeness_score,
            2,
        )

    def _count_results(self, results):
        if isinstance(results, list):
            return len(results)
        if isinstance(results, dict):
            inner = results.get("results", results.get("data", []))
            if isinstance(inner, list):
                return len(inner)
        return 0

    def _extract_markets(self, query_params, results):
        markets = set()
        if isinstance(query_params, dict):
            for k in ("market", "markets", "pos", "country"):
                v = query_params.get(k)
                if isinstance(v, list):
                    markets.update(str(m).upper() for m in v)
                elif v:
                    markets.add(str(v).upper())
        flat = results if isinstance(results, list) else (
            results.get("results", []) if isinstance(results, dict) else []
        )
        for r in (flat if isinstance(flat, list) else []):
            if isinstance(r, dict):
                m = r.get("market") or r.get("country") or r.get("pos")
                if m:
                    markets.add(str(m).upper())
        return json.dumps(sorted(markets))

    # ------------------------------------------------------------------ #
    #  Phase 2: Aggregate                                                 #
    # ------------------------------------------------------------------ #

    def aggregate_insights(self, min_observations=5, lookback_hours=168):
        """Aggregate observations into StrategyInsight records."""
        try:
            from models import StrategyObservation, StrategyInsight, db

            cutoff = datetime.utcnow() - timedelta(hours=lookback_hours)
            observations = StrategyObservation.query.filter(
                StrategyObservation.created_at >= cutoff
            ).all()

            if not observations:
                return {"categories_processed": 0, "insights_created": 0, "insights_updated": 0}

            by_category = {}
            for obs in observations:
                cat = obs.query_category or "general"
                by_category.setdefault(cat, []).append(obs)

            stats = {"categories_processed": 0, "insights_created": 0, "insights_updated": 0}

            for category, obs_list in by_category.items():
                if len(obs_list) < min_observations:
                    continue
                stats["categories_processed"] += 1

                all_insights = []
                all_insights.extend(self._aggregate_query_patterns(obs_list, category))
                all_insights.extend(self._aggregate_source_sites(obs_list, category))
                all_insights.extend(self._aggregate_market_combos(obs_list, category))
                all_insights.extend(self._aggregate_strategies(obs_list, category))

                for ins_data in all_insights:
                    insight_id = ins_data.get("insight_id")
                    existing = StrategyInsight.query.filter_by(insight_id=insight_id).first()
                    if existing:
                        existing.insight_data = json.dumps(ins_data.get("data", {}))
                        existing.confidence_score = ins_data.get("confidence", 0.5)
                        existing.observation_count = ins_data.get("observation_count", 0)
                        existing.effectiveness_score = ins_data.get("effectiveness", 0.0)
                        existing.is_active = True
                        existing.updated_at = datetime.utcnow()
                        stats["insights_updated"] += 1
                    else:
                        new_insight = StrategyInsight(
                            insight_id=insight_id,
                            category=category,
                            insight_type=ins_data.get("type", "unknown"),
                            insight_data=json.dumps(ins_data.get("data", {})),
                            confidence_score=ins_data.get("confidence", 0.5),
                            observation_count=ins_data.get("observation_count", 0),
                            effectiveness_score=ins_data.get("effectiveness", 0.0),
                            is_active=True,
                            created_at=datetime.utcnow(),
                            updated_at=datetime.utcnow(),
                        )
                        db.session.add(new_insight)
                        stats["insights_created"] += 1

            db.session.commit()

            # Build #80: Auto-retire low-performing insights
            try:
                retire_cutoff = datetime.utcnow() - timedelta(days=30)
                stale_insights = StrategyInsight.query.filter(
                    StrategyInsight.is_active == True,
                    StrategyInsight.updated_at < retire_cutoff,
                    StrategyInsight.effectiveness_score < 0.3,
                ).all()
                for ins in stale_insights:
                    ins.is_active = False
                    ins.retired_at = datetime.utcnow()
                    stats["insights_retired"] = stats.get("insights_retired", 0) + 1
                if stale_insights:
                    db.session.commit()
                    logger.info(f"Retired {len(stale_insights)} low-performing insights")
            except Exception as retire_exc:
                logger.warning(f"Auto-retire failed: {retire_exc}")

            return stats

        except Exception as exc:
            logger.warning("Failed to aggregate insights: %s", exc)
            try:
                from models import db
                db.session.rollback()
            except Exception:
                pass
            return {"categories_processed": 0, "insights_created": 0, "insights_updated": 0}

    def evaluate_strategy_effectiveness(self, hours_back=168):
        """
        Build #80: Compare enhanced vs baseline harvest performance.

        Measures if learned strategies improve data quality by comparing:
        - Tasks dispatched with enhanced prompts vs baseline
        - Success rates, avg quality scores, unique data points gathered

        Args:
            hours_back: Hours of history to analyze (default: 7 days)

        Returns:
            dict with enhanced_stats, baseline_stats, improvement_pct
        """
        try:
            from models import HarvestExecution, db

            cutoff = datetime.utcnow() - timedelta(hours=hours_back)

            # Enhanced: cycles where strategy context was applied
            enhanced = HarvestExecution.query.filter(
                HarvestExecution.started_at >= cutoff,
                HarvestExecution.metadata.contains('"strategy_enhanced":true'),
            ).all()

            # Baseline: cycles without strategy enhancement
            baseline = HarvestExecution.query.filter(
                HarvestExecution.started_at >= cutoff,
                ~HarvestExecution.metadata.contains('"strategy_enhanced":true'),
            ).all()

            def _compute_stats(executions):
                if not executions:
                    return {"count": 0, "avg_tasks": 0, "avg_gaps": 0, "avg_success_rate": 0}
                tasks = [e.tasks_dispatched or 0 for e in executions]
                gaps = [e.gaps_identified or 0 for e in executions]
                # Success rate approximation: fewer gaps = better
                success_rates = [
                    (1.0 - min(g / max(t, 1), 1.0)) for g, t in zip(gaps, tasks)
                ]
                return {
                    "count": len(executions),
                    "avg_tasks": round(sum(tasks) / len(tasks), 2) if tasks else 0,
                    "avg_gaps": round(sum(gaps) / len(gaps), 2) if gaps else 0,
                    "avg_success_rate": round(sum(success_rates) / len(success_rates), 3) if success_rates else 0,
                }

            enhanced_stats = _compute_stats(enhanced)
            baseline_stats = _compute_stats(baseline)

            improvement_pct = 0
            if baseline_stats["avg_success_rate"] > 0:
                improvement_pct = round(
                    ((enhanced_stats["avg_success_rate"] - baseline_stats["avg_success_rate"])
                     / baseline_stats["avg_success_rate"]) * 100, 1
                )

            return {
                "hours_analyzed": hours_back,
                "enhanced": enhanced_stats,
                "baseline": baseline_stats,
                "improvement_pct": improvement_pct,
                "verdict": "effective" if improvement_pct > 5 else "neutral" if improvement_pct > -5 else "ineffective",
            }

        except Exception as exc:
            logger.warning(f"evaluate_strategy_effectiveness failed: {exc}")
            return {"error": str(exc)}

    def _aggregate_query_patterns(self, observations, category):
        """Group by query_structure, rank by avg quality."""
        pattern_map = {}
        for obs in observations:
            key = obs.query_structure or "{}"
            entry = pattern_map.setdefault(key, {"scores": [], "count": 0})
            entry["scores"].append(obs.result_quality_score or 0)
            entry["count"] += 1

        insights = []
        for pattern_json, info in sorted(
            pattern_map.items(), key=lambda x: _avg(x[1]["scores"]), reverse=True
        ):
            if info["count"] < 2:
                continue
            avg_q = _avg(info["scores"])
            insight_id = f"qp_{category}_{_stable_hash(pattern_json)}"
            insights.append({
                "insight_id": insight_id,
                "type": "query_pattern",
                "data": {"pattern": _safe_json_loads(pattern_json), "avg_quality": avg_q},
                "confidence": min(info["count"] / 20.0, 1.0),
                "observation_count": info["count"],
                "effectiveness": avg_q / 100.0,
            })
        return insights[:10]

    def _aggregate_source_sites(self, observations, category):
        """Rank source sites by frequency x avg quality."""
        site_map = {}
        for obs in observations:
            sites = _safe_json_loads(obs.source_sites)
            if not isinstance(sites, list):
                continue
            quality = obs.result_quality_score or 0
            for site in sites:
                entry = site_map.setdefault(site, {"count": 0, "scores": []})
                entry["count"] += 1
                entry["scores"].append(quality)

        ranked = sorted(
            site_map.items(),
            key=lambda x: x[1]["count"] * _avg(x[1]["scores"]),
            reverse=True,
        )
        insights = []
        for site, info in ranked[:20]:
            insight_id = f"ss_{category}_{_stable_hash(site)}"
            insights.append({
                "insight_id": insight_id,
                "type": "source_site",
                "data": {"site": site, "frequency": info["count"], "avg_quality": _avg(info["scores"])},
                "confidence": min(info["count"] / 10.0, 1.0),
                "observation_count": info["count"],
                "effectiveness": _avg(info["scores"]) / 100.0,
            })
        return insights

    def _aggregate_market_combos(self, observations, category):
        """Find market combinations with highest quality."""
        combo_map = {}
        for obs in observations:
            markets = _safe_json_loads(obs.markets_searched)
            if not isinstance(markets, list) or not markets:
                continue
            key = ",".join(sorted(markets))
            entry = combo_map.setdefault(key, {"scores": [], "count": 0})
            entry["scores"].append(obs.result_quality_score or 0)
            entry["count"] += 1

        ranked = sorted(
            combo_map.items(), key=lambda x: _avg(x[1]["scores"]), reverse=True
        )
        insights = []
        for combo_key, info in ranked[:10]:
            insight_id = f"mc_{category}_{_stable_hash(combo_key)}"
            insights.append({
                "insight_id": insight_id,
                "type": "market_combo",
                "data": {"markets": combo_key.split(","), "avg_quality": _avg(info["scores"])},
                "confidence": min(info["count"] / 10.0, 1.0),
                "observation_count": info["count"],
                "effectiveness": _avg(info["scores"]) / 100.0,
            })
        return insights

    def _aggregate_strategies(self, observations, category):
        """Evaluate each strategy name by comparing quality when used vs not."""
        strategy_map = {}
        for obs in observations:
            detected = _safe_json_loads(obs.strategies_detected)
            if not isinstance(detected, list):
                continue
            quality = obs.result_quality_score or 0
            for s in detected:
                if not isinstance(s, dict):
                    continue
                name = s.get("name", "unknown")
                entry = strategy_map.setdefault(
                    name, {"used_scores": [], "unused_scores": []}
                )
                if s.get("detected"):
                    entry["used_scores"].append(quality)
                else:
                    entry["unused_scores"].append(quality)

        insights = []
        for name, info in strategy_map.items():
            used_avg = _avg(info["used_scores"])
            unused_avg = _avg(info["unused_scores"])
            total = len(info["used_scores"]) + len(info["unused_scores"])
            usage_rate = (
                len(info["used_scores"]) / total if total else 0
            )
            effectiveness = max(0, (used_avg - unused_avg) / 100.0) if unused_avg else (
                used_avg / 100.0
            )
            insight_id = f"st_{category}_{_stable_hash(name)}"
            insights.append({
                "insight_id": insight_id,
                "type": "strategy",
                "data": {
                    "name": name,
                    "usage_rate": round(usage_rate, 3),
                    "avg_quality_used": round(used_avg, 2),
                    "avg_quality_unused": round(unused_avg, 2),
                },
                "confidence": min(total / 20.0, 1.0),
                "observation_count": total,
                "effectiveness": round(effectiveness, 4),
            })
        return insights

    # ------------------------------------------------------------------ #
    #  Phase 3: Apply                                                     #
    # ------------------------------------------------------------------ #

    def enhance_prompt(self, category=None):
        """Build a prompt enhancement string from active insights."""
        try:
            from models import StrategyInsight

            query = StrategyInsight.query.filter_by(is_active=True)
            if category:
                query = query.filter_by(category=category)
            insights = query.order_by(
                StrategyInsight.effectiveness_score.desc()
            ).limit(15).all()

            if not insights:
                return None

            total_obs = sum(i.observation_count or 0 for i in insights)

            patterns = []
            sources = []
            markets = []
            strategies = []

            for ins in insights:
                data = _safe_json_loads(ins.insight_data)
                if ins.insight_type == "query_pattern":
                    pat = data.get("pattern", {})
                    desc = ", ".join(f"{k}={v}" for k, v in pat.items() if v)
                    patterns.append(f"- {desc} (quality: {data.get('avg_quality', 0):.0f})")
                elif ins.insight_type == "source_site":
                    sources.append(data.get("site", "unknown"))
                elif ins.insight_type == "market_combo":
                    m_list = data.get("markets", [])
                    cat_label = ins.category or "general"
                    markets.append(
                        f"- For {cat_label}: search {', '.join(m_list)} for best savings"
                    )
                elif ins.insight_type == "strategy":
                    sname = data.get("name", "unknown")
                    eff = ins.effectiveness_score or 0
                    strategies.append(
                        f"- {sname}: usage rate {data.get('usage_rate', 0):.0%} "
                        f"(effectiveness: {eff:.2f})"
                    )

            sections = [f"## Learned Search Strategies\n\nBased on analysis of {total_obs} successful searches:\n"]

            if patterns:
                sections.append("### Top Query Patterns:\n" + "\n".join(patterns[:5]))
            if sources:
                sections.append("### High-Value Sources:\n- " + ", ".join(sources[:10]))
            if markets:
                sections.append("### Optimal Markets:\n" + "\n".join(markets[:5]))
            if strategies:
                sections.append("### Effective Strategies:\n" + "\n".join(strategies[:5]))

            return "\n\n".join(sections)

        except Exception as exc:
            logger.warning("enhance_prompt failed: %s", exc)
            return None

    def get_strategy_sites(self, category=None, limit=20):
        """Return top source-site domains from insights."""
        try:
            from models import StrategyInsight

            query = StrategyInsight.query.filter_by(
                insight_type="source_site", is_active=True
            )
            if category:
                query = query.filter_by(category=category)
            insights = query.order_by(
                StrategyInsight.effectiveness_score.desc()
            ).limit(limit).all()

            sites = []
            for ins in insights:
                data = _safe_json_loads(ins.insight_data)
                site = data.get("site")
                if site:
                    sites.append(site)
            return sites

        except Exception as exc:
            logger.warning("get_strategy_sites failed: %s", exc)
            return []

    def get_learned_markets(self, category=None):
        """Return market codes from active market_combo insights."""
        try:
            from models import StrategyInsight

            query = StrategyInsight.query.filter_by(
                insight_type="market_combo", is_active=True
            )
            if category:
                query = query.filter_by(category=category)
            insights = query.order_by(
                StrategyInsight.effectiveness_score.desc()
            ).all()

            markets = []
            seen = set()
            for ins in insights:
                data = _safe_json_loads(ins.insight_data)
                for m in data.get("markets", []):
                    if m not in seen:
                        seen.add(m)
                        markets.append(m)
            return markets

        except Exception as exc:
            logger.warning("get_learned_markets failed: %s", exc)
            return []

    def get_learned_destinations(self, limit=30):
        """
        Build #80: Extract high-value destination airports from insights.

        Mines market_combo and strategy insights for airport codes that
        appear in high-effectiveness patterns. Returns IATA codes ranked
        by effectiveness score.

        Args:
            limit: Max destinations to return.

        Returns:
            List of IATA airport code strings, ordered by effectiveness.
        """
        try:
            from models import StrategyInsight

            insights = StrategyInsight.query.filter(
                StrategyInsight.is_active == True,
                StrategyInsight.insight_type.in_(["market_combo", "strategy", "query_pattern"]),
                StrategyInsight.effectiveness_score > 0.3,
            ).order_by(
                StrategyInsight.effectiveness_score.desc()
            ).limit(100).all()

            dest_scores = {}
            for ins in insights:
                data = _safe_json_loads(ins.insight_data)
                score = ins.effectiveness_score or 0
                # Extract destinations from insight data
                for key in ("destinations", "airports", "routes"):
                    for code in data.get(key, []):
                        code = str(code).upper().strip()
                        if len(code) == 3 and code.isalpha():
                            dest_scores[code] = max(dest_scores.get(code, 0), score)
                # Extract from route strings like "JFK-NRT"
                for route in data.get("top_routes", []):
                    if isinstance(route, str) and "-" in route:
                        parts = route.split("-")
                        for p in parts:
                            p = p.strip().upper()
                            if len(p) == 3 and p.isalpha():
                                dest_scores[p] = max(dest_scores.get(p, 0), score)

            ranked = sorted(dest_scores.items(), key=lambda x: x[1], reverse=True)
            return [code for code, _ in ranked[:limit]]

        except Exception as exc:
            logger.warning("get_learned_destinations failed: %s", exc)
            return []

    # ------------------------------------------------------------------ #
    #  Competitive Comparison                                             #
    # ------------------------------------------------------------------ #

    def run_comparison(self, user_id, byoai_results, query_params):
        """Run MystesAI against BYOAI results and compare."""
        try:
            from search import search_global

            strategy_sites = self.get_strategy_sites(
                category=query_params.get("category")
            )
            learned_markets = self.get_learned_markets(
                category=query_params.get("category")
            )

            enhanced_params = dict(query_params)
            if learned_markets:
                existing = enhanced_params.get("markets", [])
                if isinstance(existing, str):
                    existing = [existing]
                merged = list(dict.fromkeys(existing + learned_markets))
                enhanced_params["markets"] = merged
            if strategy_sites:
                enhanced_params["strategy_sites"] = strategy_sites[:10]

            mystes_results = search_global(user_id=user_id, **enhanced_params)
            if not isinstance(mystes_results, list):
                mystes_results = mystes_results.get("results", []) if isinstance(mystes_results, dict) else []

            byoai_list = byoai_results if isinstance(byoai_results, list) else (
                byoai_results.get("results", []) if isinstance(byoai_results, dict) else []
            )

            comparison = self._build_comparison(byoai_list, mystes_results)

            return {
                "byoai_results": byoai_list,
                "mystes_results": mystes_results,
                "comparison": comparison,
            }

        except Exception as exc:
            logger.warning("run_comparison failed: %s", exc)
            return {
                "error": str(exc),
                "byoai_results": byoai_results if isinstance(byoai_results, list) else [],
                "mystes_results": [],
                "comparison": {},
            }

    def _build_comparison(self, byoai_list, mystes_list):
        """Compute comparison metrics."""
        byoai_prices = self._collect_prices(byoai_list)
        mystes_prices = self._collect_prices(mystes_list)

        byoai_markets = self._collect_field(byoai_list, "market")
        mystes_markets = self._collect_field(mystes_list, "market")

        byoai_best = min(byoai_prices) if byoai_prices else None
        mystes_best = min(mystes_prices) if mystes_prices else None

        additional_savings = 0.0
        if byoai_best and mystes_best and mystes_best < byoai_best:
            additional_savings = round(byoai_best - mystes_best, 2)

        return {
            "mystes_additional_results": max(0, len(mystes_list) - len(byoai_list)),
            "additional_savings_found": additional_savings,
            "markets_covered_delta": len(mystes_markets - byoai_markets),
            "mystes_best_price": mystes_best,
            "byoai_best_price": byoai_best,
            "comparison_table": self._format_comparison_table(byoai_list, mystes_list),
        }

    def _format_comparison_table(self, byoai_results, mystes_results):
        """Build a unified comparison table sorted by price."""
        rows = []
        for r in (byoai_results if isinstance(byoai_results, list) else []):
            if not isinstance(r, dict):
                continue
            price = self._get_price(r)
            rows.append({
                "source": "Your AI",
                "item": r.get("title", r.get("airline", r.get("name", "Unknown"))),
                "price": price,
                "market": r.get("market", r.get("country", "N/A")),
                "savings_pct": 0.0,
                "is_best": False,
            })
        for r in (mystes_results if isinstance(mystes_results, list) else []):
            if not isinstance(r, dict):
                continue
            price = self._get_price(r)
            rows.append({
                "source": "MystesAI",
                "item": r.get("title", r.get("airline", r.get("name", "Unknown"))),
                "price": price,
                "market": r.get("market", r.get("country", "N/A")),
                "savings_pct": 0.0,
                "is_best": False,
            })

        rows.sort(key=lambda x: x["price"] if x["price"] is not None else float("inf"))

        # Mark best price per unique item
        best_by_item = {}
        for row in rows:
            item = row["item"]
            if item not in best_by_item or (
                row["price"] is not None
                and (best_by_item[item]["price"] is None or row["price"] < best_by_item[item]["price"])
            ):
                best_by_item[item] = row

        for row in rows:
            if row is best_by_item.get(row["item"]):
                row["is_best"] = True

        # Compute savings_pct relative to max price per item
        max_by_item = {}
        for row in rows:
            item = row["item"]
            if row["price"] is not None:
                max_by_item[item] = max(max_by_item.get(item, 0), row["price"])
        for row in rows:
            mx = max_by_item.get(row["item"])
            if mx and row["price"] is not None and mx > 0:
                row["savings_pct"] = round((1 - row["price"] / mx) * 100, 2)

        return rows

    def _collect_prices(self, results):
        prices = []
        for r in (results if isinstance(results, list) else []):
            p = self._get_price(r)
            if p is not None:
                prices.append(p)
        return prices

    def _get_price(self, item):
        if not isinstance(item, dict):
            return None
        for k in ("price", "total_price", "amount", "cost"):
            v = item.get(k)
            if v is not None:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    pass
        return None

    def _collect_field(self, results, field):
        values = set()
        for r in (results if isinstance(results, list) else []):
            if isinstance(r, dict):
                v = r.get(field)
                if v:
                    values.add(str(v).upper())
        return values

    # ------------------------------------------------------------------ #
    #  Admin Stats                                                        #
    # ------------------------------------------------------------------ #

    def get_learner_stats(self):
        """Return a stats summary for the admin dashboard."""
        try:
            from models import StrategyObservation, StrategyInsight, db

            total_obs = StrategyObservation.query.count()

            obs_by_source = {}
            for row in db.session.query(
                StrategyObservation.source_type,
                db.func.count(StrategyObservation.observation_id),
            ).group_by(StrategyObservation.source_type).all():
                obs_by_source[row[0] or "unknown"] = row[1]

            obs_by_cat = {}
            for row in db.session.query(
                StrategyObservation.query_category,
                db.func.count(StrategyObservation.observation_id),
            ).group_by(StrategyObservation.query_category).all():
                obs_by_cat[row[0] or "general"] = row[1]

            total_insights = StrategyInsight.query.filter_by(is_active=True).count()

            insights_by_type = {}
            for row in db.session.query(
                StrategyInsight.insight_type,
                db.func.count(StrategyInsight.insight_id),
            ).filter(StrategyInsight.is_active == True).group_by(
                StrategyInsight.insight_type
            ).all():
                insights_by_type[row[0] or "unknown"] = row[1]

            # Top sites
            top_sites_q = StrategyInsight.query.filter_by(
                insight_type="source_site", is_active=True
            ).order_by(StrategyInsight.effectiveness_score.desc()).limit(10).all()
            top_sites = []
            for ins in top_sites_q:
                data = _safe_json_loads(ins.insight_data)
                top_sites.append({
                    "site": data.get("site", "unknown"),
                    "effectiveness": ins.effectiveness_score,
                })

            # Top strategies
            top_strats_q = StrategyInsight.query.filter_by(
                insight_type="strategy", is_active=True
            ).order_by(StrategyInsight.effectiveness_score.desc()).limit(5).all()
            top_strategies = []
            for ins in top_strats_q:
                data = _safe_json_loads(ins.insight_data)
                top_strategies.append({
                    "name": data.get("name", "unknown"),
                    "effectiveness": ins.effectiveness_score,
                    "usage_rate": data.get("usage_rate", 0),
                })

            # Avg quality
            avg_q_row = db.session.query(
                db.func.avg(StrategyObservation.result_quality_score)
            ).scalar()
            avg_quality = round(float(avg_q_row), 2) if avg_q_row else 0.0

            # Last 24h
            cutoff_24h = datetime.utcnow() - timedelta(hours=24)
            obs_24h = StrategyObservation.query.filter(
                StrategyObservation.created_at >= cutoff_24h
            ).count()

            # Last aggregation
            last_agg_row = db.session.query(
                db.func.max(StrategyInsight.updated_at)
            ).scalar()
            last_agg = last_agg_row.isoformat() if last_agg_row else None

            return {
                "total_observations": total_obs,
                "observations_by_source": obs_by_source,
                "observations_by_category": obs_by_cat,
                "total_insights": total_insights,
                "insights_by_type": insights_by_type,
                "top_sites": top_sites,
                "top_strategies": top_strategies,
                "avg_quality_score": avg_quality,
                "observations_last_24h": obs_24h,
                "last_aggregation": last_agg,
            }

        except Exception as exc:
            logger.warning("get_learner_stats failed: %s", exc)
            return {
                "total_observations": 0,
                "observations_by_source": {},
                "observations_by_category": {},
                "total_insights": 0,
                "insights_by_type": {},
                "top_sites": [],
                "top_strategies": [],
                "avg_quality_score": 0.0,
                "observations_last_24h": 0,
                "last_aggregation": None,
            }


# -------------------------------------------------------------------- #
#  Module-level helpers                                                  #
# -------------------------------------------------------------------- #

def _safe_json_loads(value):
    """Parse a JSON string, returning the value as-is if it's already decoded."""
    if value is None:
        return {}
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {}


def _avg(scores):
    """Average of a list, 0 if empty."""
    return sum(scores) / len(scores) if scores else 0.0


def _stable_hash(text):
    """Deterministic short hash for insight IDs."""
    import hashlib
    return hashlib.sha256(str(text).encode()).hexdigest()[:12]


# -------------------------------------------------------------------- #
#  Singleton                                                             #
# -------------------------------------------------------------------- #

strategy_learner = StrategyLearner()
