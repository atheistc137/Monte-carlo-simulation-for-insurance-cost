"""Tests for per-tenor SVI calibration."""
import numpy as np
import pandas as pd
import pytest

from iv_surface_svi import assign_tenor_bucket, calibrate_svi, TENOR_BUCKETS


class TestAssignTenorBucket:
    def test_short_dated(self):
        assert assign_tenor_bucket(30) == "short"

    def test_boundary_60(self):
        assert assign_tenor_bucket(60) == "short"

    def test_90d_bucket(self):
        assert assign_tenor_bucket(90) == "90d"

    def test_180d_bucket(self):
        assert assign_tenor_bucket(180) == "180d"

    def test_270d_bucket(self):
        assert assign_tenor_bucket(270) == "270d"

    def test_365d_bucket(self):
        assert assign_tenor_bucket(365) == "365d"

    def test_edge_135(self):
        """135 is upper bound of 90d bucket."""
        assert assign_tenor_bucket(135) == "90d"

    def test_edge_136(self):
        """136 starts 180d bucket."""
        assert assign_tenor_bucket(136) == "180d"


class TestPerTenorCalibration:
    def test_calibrate_svi_returns_six_values(self):
        """SVI calibration returns (a, b, rho, m, sigma, error)."""
        k = np.array([-0.3, -0.2, -0.1, 0.0, 0.1, 0.2, 0.3])
        t = np.full_like(k, 0.25)  # 90 days
        iv = np.array([0.60, 0.55, 0.50, 0.48, 0.47, 0.48, 0.50])
        result = calibrate_svi(k, t, iv)
        assert len(result) == 6
        a, b, rho, m, sigma, err = result
        assert err < 0.1  # reasonable fit

    def test_different_tenors_produce_different_params(self):
        """90d and 365d smiles should yield different SVI params."""
        k = np.array([-0.3, -0.2, -0.1, 0.0, 0.1, 0.2, 0.3])
        # 90-day smile: steeper skew
        t_90 = np.full_like(k, 90 / 365)
        iv_90 = np.array([0.70, 0.60, 0.52, 0.48, 0.47, 0.48, 0.50])
        # 365-day smile: flatter, higher level
        t_365 = np.full_like(k, 365 / 365)
        iv_365 = np.array([0.55, 0.52, 0.50, 0.49, 0.48, 0.49, 0.50])

        params_90 = calibrate_svi(k, t_90, iv_90)
        params_365 = calibrate_svi(k, t_365, iv_365)
        # At minimum, 'a' or 'b' should differ meaningfully
        assert not np.allclose(params_90[:5], params_365[:5], atol=0.01)
