"""
optimize_backtest.py - Automated Backtest Configuration Testing

This script automates testing of different YAML configurations by:
1. Modifying the YAML parameters
2. Running the backtest via subprocess
3. Parsing results from the output
4. Generating comparison reports

Usage:
    python optimize_backtest.py quick
    python optimize_backtest.py medium
    python optimize_backtest.py full

Note: Data ingestion (run_ingest.py) only needs to be run once before optimization.
"""

import yaml
import subprocess
import os
import sys
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Tuple
import json
from itertools import product
import shutil


# ============================================================================
# CONFIGURATION
# ============================================================================

class OptimizerConfig:
    """Define parameter ranges to test."""
    
    # Base files
    BASE_CONFIG = "config/strategies_historical_adj.yaml"
    TEMP_CONFIG_DIR = "config/temp_optimization"
    RESULTS_DIR = "optimization_results"
    REPORTS_DIR = "optimization_reports"
    
    # Backtest parameters (fixed)
    START_DATE = "2024-10-14"
    END_DATE = "2024-12-15"
    VARIANT = "base"
    
    # ========================================================================
    # RISK LIMITS TO TEST
    # ========================================================================
    RISK_SCENARIOS = {
        'very_aggressive': {
            'max_position_loss_pct': 0.08,
            'max_aggregate_premium_pct': 0.35,
            'circuit_breaker_weekly_drawdown': 0.10,
        },
        'aggressive': {
            'max_position_loss_pct': 0.06,
            'max_aggregate_premium_pct': 0.28,
            'circuit_breaker_weekly_drawdown': 0.08,
        },
        'base': {
            'max_position_loss_pct': 0.04,
            'max_aggregate_premium_pct': 0.20,
            'circuit_breaker_weekly_drawdown': 0.05,
        },
        'conservative': {
            'max_position_loss_pct': 0.03,
            'max_aggregate_premium_pct': 0.15,
            'circuit_breaker_weekly_drawdown': 0.04,
        },
        'very_conservative': {
            'max_position_loss_pct': 0.025,
            'max_aggregate_premium_pct': 0.10,
            'circuit_breaker_weekly_drawdown': 0.03,
        },
    }
    
    # ========================================================================
    # STRIKE ADJUSTMENTS
    # ========================================================================
    STRIKE_SCENARIOS = {
        'base': {
            'VLO_EARNINGS_CALL_SPREAD': {'long': 130, 'short': 140},
            'AMD_EARNINGS_CALL_SPREAD': {'long': 150, 'short': 165},
            'MPC_EARNINGS_CALL_SPREAD': {'long': 145, 'short': 160},
            'KRE_BANKS_CALL_SPREAD': {'long': 55, 'short': 60},
        },
        'narrow': {
            'VLO_EARNINGS_CALL_SPREAD': {'long': 130, 'short': 135},
            'AMD_EARNINGS_CALL_SPREAD': {'long': 150, 'short': 155},
            'MPC_EARNINGS_CALL_SPREAD': {'long': 146, 'short': 151},
            'KRE_BANKS_CALL_SPREAD': {'long': 54, 'short': 57},
        },
        'wide': {
            'VLO_EARNINGS_CALL_SPREAD': {'long': 125, 'short': 140},
            'AMD_EARNINGS_CALL_SPREAD': {'long': 145, 'short': 165},
            'MPC_EARNINGS_CALL_SPREAD': {'long': 140, 'short': 160},
            'KRE_BANKS_CALL_SPREAD': {'long': 52, 'short': 60},
        },
    }
    
    # ========================================================================
    # SIZING MULTIPLIERS
    # ========================================================================
    SIZING_SCENARIOS = {
        'small': 0.7,
        'normal': 1.0,
        'large': 1.3,
    }
    
    # ========================================================================
    # STRATEGY COMBINATIONS
    # ========================================================================
    STRATEGY_SCENARIOS = {
        'all_enabled': {
            'VIX_VOL_CALL_SPREAD': False,  # No data
            'VLO_EARNINGS_CALL_SPREAD': True,
            'AMD_EARNINGS_CALL_SPREAD': True,
            'MSFT_EARNINGS_CALL_SPREAD': True,
            'MPC_EARNINGS_CALL_SPREAD': True,
            'KRE_BANKS_CALL_SPREAD': True,
            'SPY_PROTECTIVE_PUT': True,
        },
        'high_conviction': {
            'VIX_VOL_CALL_SPREAD': False,
            'VLO_EARNINGS_CALL_SPREAD': True,
            'AMD_EARNINGS_CALL_SPREAD': False,
            'MSFT_EARNINGS_CALL_SPREAD': True,
            'MPC_EARNINGS_CALL_SPREAD': False,
            'KRE_BANKS_CALL_SPREAD': True,
            'SPY_PROTECTIVE_PUT': True,
        },
        'msft_only': {
            'VIX_VOL_CALL_SPREAD': False,
            'VLO_EARNINGS_CALL_SPREAD': False,
            'AMD_EARNINGS_CALL_SPREAD': False,
            'MSFT_EARNINGS_CALL_SPREAD': True,
            'MPC_EARNINGS_CALL_SPREAD': False,
            'KRE_BANKS_CALL_SPREAD': False,
            'SPY_PROTECTIVE_PUT': True,
        },
    }


# ============================================================================
# YAML MODIFIER
# ============================================================================

class YAMLModifier:
    """Handles modification of YAML configuration files."""
    
    def __init__(self, base_config_path: str):
        self.base_config_path = Path(base_config_path)
        with open(self.base_config_path, 'r') as f:
            self.base_config = yaml.safe_load(f)
    
    def create_modified_config(
        self,
        risk_scenario: str,
        strike_scenario: str,
        sizing_scenario: str,
        strategy_scenario: str
    ) -> Dict[str, Any]:
        """Create a modified configuration based on scenario selections."""
        import copy
        config = copy.deepcopy(self.base_config)
        
        # Apply risk limits
        risk_params = OptimizerConfig.RISK_SCENARIOS[risk_scenario]
        config['risk_limits']['base'].update(risk_params)
        
        # Apply strike adjustments
        strike_adjustments = OptimizerConfig.STRIKE_SCENARIOS[strike_scenario]
        for strat_name, strikes in strike_adjustments.items():
            if strat_name in config['strategies']:
                config['strategies'][strat_name]['structure']['legs']['long']['strike_value'] = strikes['long']
                config['strategies'][strat_name]['structure']['legs']['short']['strike_value'] = strikes['short']
        
        # Apply sizing multiplier
        sizing_mult = OptimizerConfig.SIZING_SCENARIOS[sizing_scenario]
        for strat_name in config['strategies']:
            if 'position_sizing' in config['strategies'][strat_name]:
                base_size = config['strategies'][strat_name]['position_sizing']['base']
                config['strategies'][strat_name]['position_sizing']['base'] = int(base_size * sizing_mult)
        
        # Apply strategy enable/disable
        strategy_settings = OptimizerConfig.STRATEGY_SCENARIOS[strategy_scenario]
        for strat_name, enabled in strategy_settings.items():
            if strat_name in config['strategies']:
                config['strategies'][strat_name]['enabled'] = enabled
        
        return config
    
    def save_config(self, config: Dict[str, Any], output_path: Path) -> None:
        """Save modified config to file."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)


# ============================================================================
# BACKTEST RUNNER
# ============================================================================

class BacktestRunner:
    """Runs backtests and parses results."""
    
    def __init__(self):
        self.run_counter = 0
    
    def run_backtest(self, config_path: Path) -> Dict[str, Any]:
        """Execute backtest subprocess and parse results."""
        self.run_counter += 1
        
        cmd = [
            'python', 'run_backtest.py',
            '--config', str(config_path),
            '--start', OptimizerConfig.START_DATE,
            '--end', OptimizerConfig.END_DATE,
            '--variant', OptimizerConfig.VARIANT
        ]
        
        try:
            result = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True, 
                timeout=120
            )
            
            output = result.stdout + result.stderr
            return self._parse_output(output, config_path)
            
        except subprocess.TimeoutExpired:
            return {
                'success': False,
                'error': 'Timeout (>120s)',
                'config_file': str(config_path)
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'config_file': str(config_path)
            }
    
    def _parse_output(self, output: str, config_path: Path) -> Dict[str, Any]:
        """Extract metrics from backtest output."""
        result = {
            'success': False,
            'config_file': str(config_path),
            'final_nav': 0.0,
            'total_return': 0.0,
            'max_drawdown': 0.0,
            'sharpe_ratio': 0.0,
            'win_rate': 0.0,
            'num_trades': 0,
            'circuit_breaker_hit': False,
            'blocked_trades': [],
            'raw_output': output
        }
        
        # Parse line by line
        for line in output.split('\n'):
            if 'BACKTEST COMPLETE' in line:
                result['success'] = True
            
            elif 'Final NAV:' in line:
                try:
                    # Extract: "Final NAV: $15,254.00"
                    match = re.search(r'\$([0-9,]+\.\d{2})', line)
                    if match:
                        result['final_nav'] = float(match.group(1).replace(',', ''))
                except:
                    pass
            
            elif 'Total Return:' in line:
                try:
                    # Extract: "Total Return: +52.54%"
                    match = re.search(r'([+-]?\d+\.\d+)%', line)
                    if match:
                        result['total_return'] = float(match.group(1))
                except:
                    pass
            
            elif 'Max Drawdown:' in line:
                try:
                    match = re.search(r'(\d+\.\d+)%', line)
                    if match:
                        result['max_drawdown'] = float(match.group(1))
                except:
                    pass
            
            elif 'Sharpe Ratio:' in line:
                try:
                    match = re.search(r'(\d+\.\d+)', line)
                    if match:
                        result['sharpe_ratio'] = float(match.group(1))
                except:
                    pass
            
            elif 'Win Rate:' in line:
                try:
                    match = re.search(r'(\d+\.\d+)%', line)
                    if match:
                        result['win_rate'] = float(match.group(1))
                except:
                    pass
            
            elif 'ENTRY:' in line:
                result['num_trades'] += 1
            
            elif 'CIRCUIT BREAKER' in line:
                result['circuit_breaker_hit'] = True
            
            elif 'Cannot open' in line:
                # Track which strategies were blocked
                match = re.search(r'Cannot open (\w+):', line)
                if match:
                    result['blocked_trades'].append(match.group(1))
        
        return result


# ============================================================================
# OPTIMIZER
# ============================================================================

class BacktestOptimizer:
    """Main optimizer class."""
    
    def __init__(self, test_mode='full'):
        """
        Initialize optimizer.
        
        Args:
            test_mode: 'full' for all parameters, 'risk' for risk-only testing
        """
        self.test_mode = test_mode
        self.yaml_modifier = YAMLModifier(OptimizerConfig.BASE_CONFIG)
        self.runner = BacktestRunner()
        self.results = []
        
        # Setup directories based on test mode
        self.temp_dir = Path(OptimizerConfig.TEMP_CONFIG_DIR)
        
        if test_mode == 'risk':
            self.results_dir = Path('risk_optimization_results')
            self.reports_dir = Path('risk_optimization_reports')
        else:
            self.results_dir = Path(OptimizerConfig.RESULTS_DIR)
            self.reports_dir = Path(OptimizerConfig.REPORTS_DIR)
        
        # Clean previous results
        self._clean_previous_results()
        
        # Create fresh directories
        self.temp_dir.mkdir(exist_ok=True)
        self.results_dir.mkdir(exist_ok=True)
        self.reports_dir.mkdir(exist_ok=True)
    
    def _clean_previous_results(self):
        """Remove all files from previous optimization runs."""
        # Clean results directory
        if self.results_dir.exists():
            for file in self.results_dir.glob('*'):
                if file.is_file():
                    file.unlink()
            print(f"🧹 Cleaned previous results from {self.results_dir}")
        
        # Clean reports directory
        if self.reports_dir.exists():
            for file in self.reports_dir.glob('*'):
                if file.is_file():
                    file.unlink()
            print(f"🧹 Cleaned previous reports from {self.reports_dir}")
        
        # Clean temp directory
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
            print(f"🧹 Cleaned temp configs from {self.temp_dir}")
        
        print()
    
    def run_quick_test(self):
        """Quick test with 4-6 configurations."""
        print("\n" + "="*70)
        print("QUICK TEST MODE - Testing 6 configurations")
        print("="*70 + "\n")
        
        test_configs = [
            ('very_aggressive', 'base', 'normal', 'all_enabled'),
            ('aggressive', 'narrow', 'normal', 'all_enabled'),
            ('base', 'wide', 'small', 'all_enabled'),
            ('base', 'base', 'normal', 'high_conviction'),
            ('conservative', 'narrow', 'small', 'high_conviction'),
            ('very_conservative', 'base', 'large', 'msft_only'),
        ]
        
        for risk, strikes, sizing, strategies in test_configs:
            self._run_single_test(risk, strikes, sizing, strategies)
        
        self._print_summary()
        self._save_results()
    
    def run_risk_only_quick(self):
        """Quick risk-only test - test a few key risk combinations."""
        print("\n" + "="*70)
        print("RISK-ONLY QUICK TEST - Testing 6 risk combinations")
        print("="*70 + "\n")
        
        # Test combinations of risk parameters, keeping strikes/sizing/strategies at base
        test_configs = [
            (0.08, 0.35, 0.10),  # Very aggressive
            (0.06, 0.28, 0.08),  # Aggressive
            (0.04, 0.20, 0.05),  # Base
            (0.03, 0.15, 0.04),  # Conservative
            (0.025, 0.10, 0.03), # Very conservative
            (0.05, 0.25, 0.06),  # Mixed
        ]
        
        for max_loss, max_agg, cb in test_configs:
            self._run_risk_only_test(max_loss, max_agg, cb)
        
        self._print_summary()
        self._save_results()
    
    def run_risk_only_medium(self):
        """Medium risk-only grid - test various combinations."""
        print("\n" + "="*70)
        print("RISK-ONLY MEDIUM GRID")
        print("="*70 + "\n")
        
        max_loss_values = [0.025, 0.03, 0.04, 0.06, 0.08]
        max_agg_values = [0.15, 0.20, 0.28]
        cb_values = [0.04, 0.05, 0.08]
        
        total = len(list(product(max_loss_values, max_agg_values, cb_values)))
        print(f"Total risk configurations to test: {total}\n")
        
        for max_loss, max_agg, cb in product(max_loss_values, max_agg_values, cb_values):
            self._run_risk_only_test(max_loss, max_agg, cb)
        
        self._print_summary()
        self._save_results()
    
    def run_risk_only_full(self):
        """Full risk-only grid - exhaustive test of all risk combinations."""
        print("\n" + "="*70)
        print("RISK-ONLY FULL GRID")
        print("="*70 + "\n")
        
        # Finer granularity for full test
        max_loss_values = [0.025, 0.03, 0.035, 0.04, 0.05, 0.06, 0.07, 0.08]
        max_agg_values = [0.10, 0.15, 0.20, 0.25, 0.28, 0.30, 0.35]
        cb_values = [0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.10]
        
        total = len(list(product(max_loss_values, max_agg_values, cb_values)))
        print(f"Total risk configurations to test: {total}\n")
        
        for max_loss, max_agg, cb in product(max_loss_values, max_agg_values, cb_values):
            self._run_risk_only_test(max_loss, max_agg, cb)
        
        self._print_summary()
        self._save_results()
    
    def run_medium_grid(self):
        """Medium grid search."""
        print("\n" + "="*70)
        print("MEDIUM GRID MODE")
        print("="*70 + "\n")
        
        risk_scenarios = ['aggressive', 'base', 'conservative']
        strike_scenarios = ['base', 'narrow', 'wide']
        sizing_scenarios = ['small', 'normal']
        strategy_scenarios = ['all_enabled', 'high_conviction']
        
        total = len(list(product(risk_scenarios, strike_scenarios, sizing_scenarios, strategy_scenarios)))
        print(f"Total configurations to test: {total}\n")
        
        for risk, strikes, sizing, strategies in product(
            risk_scenarios, strike_scenarios, sizing_scenarios, strategy_scenarios
        ):
            self._run_single_test(risk, strikes, sizing, strategies)
        
        self._print_summary()
        self._save_results()
    
    def run_full_grid(self):
        """Full exhaustive search."""
        print("\n" + "="*70)
        print("FULL GRID MODE - This will take 15-30 minutes!")
        print("="*70 + "\n")
        
        risk_scenarios = list(OptimizerConfig.RISK_SCENARIOS.keys())
        strike_scenarios = list(OptimizerConfig.STRIKE_SCENARIOS.keys())
        sizing_scenarios = list(OptimizerConfig.SIZING_SCENARIOS.keys())
        strategy_scenarios = list(OptimizerConfig.STRATEGY_SCENARIOS.keys())
        
        total = len(list(product(risk_scenarios, strike_scenarios, sizing_scenarios, strategy_scenarios)))
        print(f"Total configurations to test: {total}\n")
        
        for risk, strikes, sizing, strategies in product(
            risk_scenarios, strike_scenarios, sizing_scenarios, strategy_scenarios
        ):
            self._run_single_test(risk, strikes, sizing, strategies)
        
        self._print_summary()
        self._save_results()
    
    def _run_single_test(
        self,
        risk_scenario: str,
        strike_scenario: str,
        sizing_scenario: str,
        strategy_scenario: str
    ):
        """Run a single backtest configuration."""
        run_num = len(self.results) + 1
        config_name = f"{risk_scenario}_{strike_scenario}_{sizing_scenario}_{strategy_scenario}"
        
        print(f"[{run_num}] Testing: {config_name}")
        print(f"     Risk: {risk_scenario} | Strikes: {strike_scenario} | Size: {sizing_scenario} | Strategies: {strategy_scenario}")
        
        # Create modified config
        config = self.yaml_modifier.create_modified_config(
            risk_scenario, strike_scenario, sizing_scenario, strategy_scenario
        )
        
        # Save to temp file
        config_path = self.temp_dir / f"config_{run_num:03d}_{config_name}.yaml"
        self.yaml_modifier.save_config(config, config_path)
        
        # Run backtest
        result = self.runner.run_backtest(config_path)
        
        # Move generated reports to optimization_reports with proper naming
        self._move_reports_to_optimization_folder(config_name)
        
        # Store configuration details with result
        result['config_name'] = config_name
        result['risk_scenario'] = risk_scenario
        result['strike_scenario'] = strike_scenario
        result['sizing_scenario'] = sizing_scenario
        result['strategy_scenario'] = strategy_scenario
        result['risk_params'] = OptimizerConfig.RISK_SCENARIOS[risk_scenario]
        
        self.results.append(result)
        
        # Print result
        if result['success']:
            print(f"     ✅ Return: {result['total_return']:+.1f}% | Trades: {result['num_trades']} | Max DD: {result['max_drawdown']:.1f}% | Sharpe: {result['sharpe_ratio']:.2f}")
            if result['blocked_trades']:
                print(f"     ⚠️  Blocked: {', '.join(result['blocked_trades'])}")
        else:
            print(f"     ❌ Failed: {result.get('error', 'Unknown error')}")
        
        print()
    
    def _run_risk_only_test(
        self,
        max_position_loss_pct: float,
        max_aggregate_premium_pct: float,
        circuit_breaker_weekly_drawdown: float
    ):
        """Run a risk-only test with specific risk parameters."""
        run_num = len(self.results) + 1
        config_name = f"risktest_{max_position_loss_pct:.3f}_{max_aggregate_premium_pct:.2f}_{circuit_breaker_weekly_drawdown:.2f}"
        
        print(f"[{run_num}] Testing: {config_name}")
        print(f"     Max Loss: {max_position_loss_pct*100:.1f}% | Max Agg: {max_aggregate_premium_pct*100:.0f}% | CB: {circuit_breaker_weekly_drawdown*100:.0f}%")
        
        # Create config with only risk parameters changed, everything else at base
        import copy
        config = copy.deepcopy(self.yaml_modifier.base_config)
        
        # Apply only risk limits
        config['risk_limits']['base']['max_position_loss_pct'] = max_position_loss_pct
        config['risk_limits']['base']['max_aggregate_premium_pct'] = max_aggregate_premium_pct
        config['risk_limits']['base']['circuit_breaker_weekly_drawdown'] = circuit_breaker_weekly_drawdown
        
        # Keep strikes at base values (from original yaml)
        # Keep sizing at base values (no multiplier)
        # Keep strategies at base (all enabled except VIX)
        
        # Save to temp file
        config_path = self.temp_dir / f"config_{run_num:03d}_{config_name}.yaml"
        self.yaml_modifier.save_config(config, config_path)
        
        # Run backtest
        result = self.runner.run_backtest(config_path)
        
        # Move reports
        self._move_reports_to_optimization_folder(config_name)
        
        # Store results
        result['config_name'] = config_name
        result['max_position_loss_pct'] = max_position_loss_pct
        result['max_aggregate_premium_pct'] = max_aggregate_premium_pct
        result['circuit_breaker_weekly_drawdown'] = circuit_breaker_weekly_drawdown
        result['risk_params'] = {
            'max_position_loss_pct': max_position_loss_pct,
            'max_aggregate_premium_pct': max_aggregate_premium_pct,
            'circuit_breaker_weekly_drawdown': circuit_breaker_weekly_drawdown,
        }
        
        self.results.append(result)
        
        # Print result
        if result['success']:
            print(f"     ✅ Return: {result['total_return']:+.1f}% | Trades: {result['num_trades']} | Max DD: {result['max_drawdown']:.1f}% | Sharpe: {result['sharpe_ratio']:.2f}")
            if result['blocked_trades']:
                print(f"     ⚠️  Blocked: {', '.join(result['blocked_trades'])}")
        else:
            print(f"     ❌ Failed: {result.get('error', 'Unknown error')}")
        
        print()
    
    def _move_reports_to_optimization_folder(self, config_name: str):
        """Move generated backtest reports to optimization_reports folder with readable names."""
        outputs_dir = Path('outputs')
        if not outputs_dir.exists():
            return
        
        # Find most recent report files
        report_files = list(outputs_dir.glob('report_*.txt'))
        daily_files = list(outputs_dir.glob('daily_metrics_*.csv'))
        trade_files = list(outputs_dir.glob('trade_log_*.csv'))
        signal_files = list(outputs_dir.glob('signals_*.csv'))
        
        # Get most recent of each type
        if report_files:
            latest_report = max(report_files, key=lambda p: p.stat().st_mtime)
            new_report_path = self.reports_dir / f"report_{config_name}.txt"
            shutil.move(str(latest_report), str(new_report_path))
        
        if daily_files:
            latest_daily = max(daily_files, key=lambda p: p.stat().st_mtime)
            new_daily_path = self.reports_dir / f"daily_metrics_{config_name}.csv"
            shutil.move(str(latest_daily), str(new_daily_path))
        
        if trade_files:
            latest_trade = max(trade_files, key=lambda p: p.stat().st_mtime)
            new_trade_path = self.reports_dir / f"trade_log_{config_name}.csv"
            shutil.move(str(latest_trade), str(new_trade_path))
        
        if signal_files:
            latest_signal = max(signal_files, key=lambda p: p.stat().st_mtime)
            new_signal_path = self.reports_dir / f"signals_{config_name}.csv"
            shutil.move(str(latest_signal), str(new_signal_path))
    
    def _print_summary(self):
        """Print optimization summary."""
        print("\n" + "="*70)
        print("OPTIMIZATION SUMMARY")
        print("="*70 + "\n")
        
        successful = [r for r in self.results if r['success']]
        
        if not successful:
            print("❌ No successful runs!")
            return
        
        print(f"Successful Runs: {len(successful)}/{len(self.results)}\n")
        
        # Sort by return
        by_return = sorted(successful, key=lambda x: x['total_return'], reverse=True)
        
        print("Top 5 Configurations by Return:\n")
        for i, result in enumerate(by_return[:5], 1):
            self._print_result_summary(i, result)
        
        # Risk-adjusted ranking
        print("\nTop 5 by Risk-Adjusted Return (Return / Max DD):")
        print("(Excluding configurations with Max DD of 0.00%)\n")
        
        # Filter out zero drawdown
        non_zero_dd = [r for r in successful if r['max_drawdown'] > 0.01]
        if non_zero_dd:
            risk_adjusted = [(r, r['total_return'] / r['max_drawdown']) for r in non_zero_dd]
            risk_adjusted.sort(key=lambda x: x[1], reverse=True)
            
            for i, (result, ratio) in enumerate(risk_adjusted[:5], 1):
                print(f"{i}. {result['config_name']}")
                print(f"   Ratio: {ratio:.2f} | Return: {result['total_return']:+.1f}% | DD: {result['max_drawdown']:.2f}% | Sharpe: {result['sharpe_ratio']:.2f}")
                print(f"   Trades: {result['num_trades']} | Win Rate: {result['win_rate']:.1f}%")
                
                # Show risk parameters for risk-only tests
                if self.test_mode == 'risk':
                    params = result.get('risk_params', {})
                    print(f"   Max Loss: {params.get('max_position_loss_pct', 0)*100:.1f}% | " +
                          f"Max Agg: {params.get('max_aggregate_premium_pct', 0)*100:.0f}% | " +
                          f"CB: {params.get('circuit_breaker_weekly_drawdown', 0)*100:.0f}%")
                else:
                    print(f"   Risk: {result.get('risk_scenario', 'N/A')} | Strikes: {result.get('strike_scenario', 'N/A')} | Size: {result.get('sizing_scenario', 'N/A')}")
                
                print()
        else:
            print("No configurations with non-zero drawdown found.\n")
        
        # Most trades executed
        print("\nConfigurations with Most Trades:\n")
        by_trades = sorted(successful, key=lambda x: x['num_trades'], reverse=True)
        for i, result in enumerate(by_trades[:3], 1):
            print(f"{i}. {result['config_name']}")
            print(f"   Return: {result['total_return']:+.1f}% | Trades: {result['num_trades']} | Max DD: {result['max_drawdown']:.2f}% | Sharpe: {result['sharpe_ratio']:.2f}")
            print(f"   Win Rate: {result['win_rate']:.1f}%")
            print()
    
    def _print_result_summary(self, rank: int, result: Dict[str, Any]):
        """Print a single result in consistent format."""
        print(f"{rank}. {result['config_name']}")
        print(f"   Return: {result['total_return']:+.1f}% | Trades: {result['num_trades']} | Max DD: {result['max_drawdown']:.2f}% | Sharpe: {result['sharpe_ratio']:.2f}")
        print(f"   Win Rate: {result['win_rate']:.1f}%")
        
        if self.test_mode == 'risk':
            # Show risk parameters
            params = result.get('risk_params', {})
            print(f"   Max Loss: {params.get('max_position_loss_pct', 0)*100:.1f}% | " +
                  f"Max Agg: {params.get('max_aggregate_premium_pct', 0)*100:.0f}% | " +
                  f"CB: {params.get('circuit_breaker_weekly_drawdown', 0)*100:.0f}%")
        else:
            # Show full scenario parameters
            print(f"   Risk: {result.get('risk_scenario', 'N/A')} | Strikes: {result.get('strike_scenario', 'N/A')} | Size: {result.get('sizing_scenario', 'N/A')}")
        
        print(f"   Config: {result['config_file']}")
        if result.get('circuit_breaker_hit'):
            print(f"   ⚠️  Circuit breaker triggered")
        print()
    
    def _save_results(self):
        """Save results to JSON file."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        results_file = self.results_dir / f"optimization_results_{timestamp}.json"
        
        # Clean results for JSON (remove raw output)
        clean_results = []
        for r in self.results:
            clean_r = {k: v for k, v in r.items() if k != 'raw_output'}
            clean_results.append(clean_r)
        
        with open(results_file, 'w') as f:
            json.dump(clean_results, f, indent=2, default=str)
        
        print(f"\n📊 Full results saved to: {results_file}")
        
        # Also save a CSV summary
        csv_file = self.results_dir / f"optimization_summary_{timestamp}.csv"
        with open(csv_file, 'w', encoding='utf-8') as f:
            if self.test_mode == 'risk':
                f.write("config_name,max_position_loss_pct,max_aggregate_premium_pct,circuit_breaker_weekly_drawdown,success,total_return,max_drawdown,sharpe_ratio,win_rate,num_trades,circuit_breaker\n")
                for r in self.results:
                    f.write(f"{r['config_name']},{r.get('max_position_loss_pct', 0):.3f},{r.get('max_aggregate_premium_pct', 0):.2f},{r.get('circuit_breaker_weekly_drawdown', 0):.2f},")
                    f.write(f"{r['success']},{r['total_return']:.2f},{r['max_drawdown']:.2f},{r['sharpe_ratio']:.2f},{r['win_rate']:.2f},{r['num_trades']},{r['circuit_breaker_hit']}\n")
            else:
                f.write("config_name,risk_scenario,strike_scenario,sizing_scenario,strategy_scenario,success,total_return,max_drawdown,sharpe_ratio,win_rate,num_trades,circuit_breaker\n")
                for r in self.results:
                    f.write(f"{r['config_name']},{r.get('risk_scenario', 'N/A')},{r.get('strike_scenario', 'N/A')},{r.get('sizing_scenario', 'N/A')},{r.get('strategy_scenario', 'N/A')},")
                    f.write(f"{r['success']},{r['total_return']:.2f},{r['max_drawdown']:.2f},{r['sharpe_ratio']:.2f},{r['win_rate']:.2f},{r['num_trades']},{r['circuit_breaker_hit']}\n")
        
        print(f"📊 CSV summary saved to: {csv_file}")
        
        # Save top ranked configurations
        self._save_top_ranked_configs(timestamp)
        
        print(f"📁 Individual reports saved to: {self.reports_dir}")
    
    def _save_top_ranked_configs(self, timestamp: str):
        """Save detailed rankings of top configurations to a text file."""
        rankings_file = self.results_dir / f"top_ranked_configs_{timestamp}.txt"
        
        successful = [r for r in self.results if r['success']]
        
        if not successful:
            with open(rankings_file, 'w') as f:
                f.write("No successful runs to rank.\n")
            return
        
        lines = [
            "=" * 80,
            "TOP RANKED CONFIGURATIONS",
            "=" * 80,
            "",
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Test Mode: {self.test_mode.upper()}",
            f"Total Successful Runs: {len(successful)}/{len(self.results)}",
            "",
        ]
        
        # 1. Top 10 by Return
        lines.extend([
            "=" * 80,
            "TOP 10 CONFIGURATIONS BY TOTAL RETURN",
            "=" * 80,
            "",
        ])
        
        by_return = sorted(successful, key=lambda x: x['total_return'], reverse=True)
        for i, result in enumerate(by_return[:10], 1):
            lines.extend(self._format_ranking_entry(i, result))
        
        # 2. Top 10 by Risk-Adjusted Return (excluding zero drawdown)
        lines.extend([
            "",
            "=" * 80,
            "TOP 10 CONFIGURATIONS BY RISK-ADJUSTED RETURN (Return / Max DD)",
            "(Excluding configurations with Max DD of 0.00%)",
            "=" * 80,
            "",
        ])
        
        # Filter out zero drawdown configs
        non_zero_dd = [r for r in successful if r['max_drawdown'] > 0.01]
        risk_adjusted = [(r, r['total_return'] / r['max_drawdown']) for r in non_zero_dd]
        risk_adjusted.sort(key=lambda x: x[1], reverse=True)
        
        if not risk_adjusted:
            lines.append("No configurations with non-zero drawdown found.\n")
        else:
            for i, (result, ratio) in enumerate(risk_adjusted[:10], 1):
                lines.append(f"{i}. {result['config_name']}")
                lines.append(f"   Risk-Adjusted Ratio: {ratio:.2f}")
                lines.append(f"   Return: {result['total_return']:+.2f}% | Max DD: {result['max_drawdown']:.2f}% | Sharpe: {result['sharpe_ratio']:.2f}")
                lines.append(f"   Trades: {result['num_trades']} | Win Rate: {result['win_rate']:.2f}%")
                self._add_param_line(lines, result)
                lines.append("")
        
        # 3. Top 10 by Smallest Max Drawdown (excluding zero)
        lines.extend([
            "=" * 80,
            "TOP 10 CONFIGURATIONS BY SMALLEST MAX DRAWDOWN",
            "(Excluding configurations with Max DD of 0.00%)",
            "=" * 80,
            "",
        ])
        
        by_drawdown = sorted(non_zero_dd, key=lambda x: x['max_drawdown'])
        if not by_drawdown:
            lines.append("No configurations with non-zero drawdown found.\n")
        else:
            for i, result in enumerate(by_drawdown[:10], 1):
                lines.extend(self._format_ranking_entry(i, result))
        
        # 4. Top 5 by Highest Sharpe Ratio
        lines.extend([
            "=" * 80,
            "TOP 5 CONFIGURATIONS BY HIGHEST SHARPE RATIO",
            "=" * 80,
            "",
        ])
        
        by_sharpe = sorted(successful, key=lambda x: x['sharpe_ratio'], reverse=True)
        for i, result in enumerate(by_sharpe[:5], 1):
            lines.extend(self._format_ranking_entry(i, result))
        
        # 5. Top 5 by Most Trades Executed
        lines.extend([
            "=" * 80,
            "TOP 5 CONFIGURATIONS BY MOST TRADES EXECUTED",
            "=" * 80,
            "",
        ])
        
        by_trades = sorted(successful, key=lambda x: x['num_trades'], reverse=True)
        for i, result in enumerate(by_trades[:5], 1):
            lines.extend(self._format_ranking_entry(i, result))
        
        lines.extend([
            "=" * 80,
            "END OF RANKINGS",
            "=" * 80,
        ])
        
        # Write to file
        with open(rankings_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(lines))
        
        print(f"🏆 Top ranked configs saved to: {rankings_file}")
    
    def _format_ranking_entry(self, rank: int, result: Dict[str, Any]) -> List[str]:
        """Format a single ranking entry for the file."""
        lines = [
            f"{rank}. {result['config_name']}",
            f"   Return: {result['total_return']:+.2f}% | Trades: {result['num_trades']} | Max DD: {result['max_drawdown']:.2f}% | Sharpe: {result['sharpe_ratio']:.2f}",
            f"   Win Rate: {result['win_rate']:.2f}%",
        ]
        
        self._add_param_line(lines, result)
        
        if result.get('circuit_breaker_hit'):
            lines.append("   ⚠️  Circuit breaker triggered")
        
        if result.get('blocked_trades'):
            lines.append(f"   ⚠️  Blocked trades: {', '.join(result['blocked_trades'])}")
        
        lines.append("")
        return lines
    
    def _add_param_line(self, lines: List[str], result: Dict[str, Any]) -> None:
        """Add parameter line based on test mode."""
        if self.test_mode == 'risk':
            params = result.get('risk_params', {})
            lines.append(
                f"   Max Loss: {params.get('max_position_loss_pct', 0)*100:.1f}% | " +
                f"Max Agg: {params.get('max_aggregate_premium_pct', 0)*100:.0f}% | " +
                f"CB: {params.get('circuit_breaker_weekly_drawdown', 0)*100:.0f}%"
            )
        else:
            lines.append(
                f"   Risk: {result.get('risk_scenario', 'N/A')} | " +
                f"Strikes: {result.get('strike_scenario', 'N/A')} | " +
                f"Size: {result.get('sizing_scenario', 'N/A')} | " +
                f"Strategies: {result.get('strategy_scenario', 'N/A')}"
            )
    
    def cleanup(self):
        """Remove temporary config files."""
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
        print("\n🧹 Cleaned up temporary config files")


# ============================================================================
# MAIN
# ============================================================================

def main():
    if len(sys.argv) < 2:
        print("Usage: python optimize_backtest.py [MODE] [SPEED]")
        print("\nModes:")
        print("  full   - Test all parameters (risk, strikes, sizing, strategies)")
        print("  risk   - Test only risk parameters (keeps others at base)")
        print("\nSpeeds:")
        print("  quick  - Test 6 key configurations (~3-5 min)")
        print("  medium - Test ~36 configurations (~15-20 min)")
        print("  full   - Test all combinations (~30-45 min)")
        print("\nExamples:")
        print("  python optimize_backtest.py full quick")
        print("  python optimize_backtest.py risk medium")
        sys.exit(1)
    
    # Parse arguments
    if len(sys.argv) == 2:
        # Old style: just speed (backward compatible)
        speed = sys.argv[1].lower()
        mode = 'full'
    else:
        mode = sys.argv[1].lower()
        speed = sys.argv[2].lower()
    
    if mode not in ['full', 'risk']:
        print(f"Invalid mode: {mode}")
        print("Choose: full or risk")
        sys.exit(1)
    
    if speed not in ['quick', 'medium', 'full']:
        print(f"Invalid speed: {speed}")
        print("Choose: quick, medium, or full")
        sys.exit(1)
    
    # Check if data exists
    data_file = Path('data/raw/equities_ohlcv.csv')
    if not data_file.exists():
        print("\n⚠️  Data not found! Please run first:")
        print("    python run_ingest.py\n")
        sys.exit(1)
    
    # Run optimization
    optimizer = BacktestOptimizer(test_mode=mode)
    
    try:
        if mode == 'risk':
            # Risk-only testing
            if speed == 'quick':
                optimizer.run_risk_only_quick()
            elif speed == 'medium':
                optimizer.run_risk_only_medium()
            elif speed == 'full':
                optimizer.run_risk_only_full()
        else:
            # Full parameter testing
            if speed == 'quick':
                optimizer.run_quick_test()
            elif speed == 'medium':
                optimizer.run_medium_grid()
            elif speed == 'full':
                optimizer.run_full_grid()
    finally:
        optimizer.cleanup()
    
    print("\n✅ Optimization complete!")


if __name__ == "__main__":
    main()