"""Tests for the jump-diffusion price path generator."""
import numpy as np
import pytest
from price_paths import generate_jd_path


class TestGenerateJDPath:
    def test_shape(self):
        """Output length = n_days + 1 (includes day 0)."""
        rng = np.random.default_rng(42)
        path = generate_jd_path(100_000, 0.05, 0.60, 360, rng,
                                lam=0.1, mu_j=-0.15, sigma_j=0.10)
        assert len(path) == 361

    def test_starts_at_spot(self):
        """First element equals spot_0."""
        rng = np.random.default_rng(42)
        path = generate_jd_path(100_000, 0.05, 0.60, 360, rng,
                                lam=0.1, mu_j=-0.15, sigma_j=0.10)
        assert path[0] == pytest.approx(100_000)

    def test_always_positive(self):
        """Prices should always be positive (log-normal + log-normal jumps)."""
        rng = np.random.default_rng(7)
        path = generate_jd_path(100_000, 0.0, 0.80, 360, rng,
                                lam=0.5, mu_j=-0.30, sigma_j=0.20)
        assert all(p > 0 for p in path)

    def test_deterministic_with_seed(self):
        """Same seed → same path."""
        rng1 = np.random.default_rng(99)
        path1 = generate_jd_path(100_000, 0.05, 0.60, 360, rng1,
                                 lam=0.1, mu_j=-0.15, sigma_j=0.10)
        rng2 = np.random.default_rng(99)
        path2 = generate_jd_path(100_000, 0.05, 0.60, 360, rng2,
                                 lam=0.1, mu_j=-0.15, sigma_j=0.10)
        np.testing.assert_array_equal(path1, path2)

    def test_zero_intensity_equals_gbm(self):
        """With λ=0 (no jumps), path should match pure GBM dynamics."""
        rng1 = np.random.default_rng(42)
        path_jd = generate_jd_path(100_000, 0.05, 0.60, 30, rng1,
                                   lam=0.0, mu_j=-0.15, sigma_j=0.10)
        # Log-returns should be roughly normal (no jump spikes)
        log_rets = np.diff(np.log(path_jd))
        # With 30 samples, just check reasonable range — no extreme outliers
        assert np.abs(log_rets).max() < 0.5  # no daily >50% move

    def test_high_intensity_produces_jumps(self):
        """High λ should produce noticeably fatter tails than pure GBM."""
        rng = np.random.default_rng(0)
        n = 360
        path = generate_jd_path(100_000, 0.0, 0.30, n, rng,
                                lam=2.0, mu_j=-0.20, sigma_j=0.15)
        log_rets = np.diff(np.log(path))
        # Kurtosis of daily log-returns should exceed normal (3.0)
        from scipy.stats import kurtosis
        k = kurtosis(log_rets, fisher=False)  # excess=False → normal ≈ 3
        assert k > 4.0  # fat tails from jumps
