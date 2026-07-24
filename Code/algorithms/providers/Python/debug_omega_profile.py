from __future__ import annotations

import argparse
import cProfile
import pstats
from dataclasses import replace
from datetime import datetime, timedelta
from time import perf_counter

import numpy as np

from algorithms.omega import (
    OmegaConfig,
    execute_omega_retrieval,
    make_date_blocks,
    retrieve_omega_pixel_timeseries,
)


def _build_date_keys(nt: int, step_days: int) -> list[str]:
    start = datetime(2020, 1, 1)
    return [
        (start + timedelta(days=step_days * idx)).strftime("%Y%m%d")
        for idx in range(nt)
    ]


def _build_payload(
    nt: int, npix: int, *, dual_temp: bool, seed: int
) -> dict[str, object]:
    rng = np.random.default_rng(seed)
    time_axis = np.linspace(0.0, 2.0 * np.pi, nt, dtype=np.float64).reshape(nt, 1)
    pixel_phase = rng.uniform(0.0, np.pi, size=(1, npix))
    pixel_scale = rng.uniform(0.85, 1.15, size=(1, npix))

    sm_ref = np.clip(
        0.22
        + 0.05 * np.sin(time_axis + pixel_phase)
        + 0.01 * rng.standard_normal((nt, npix)),
        0.05,
        0.45,
    )
    ndvi = np.clip(0.42 + 0.25 * np.sin(time_axis + 0.5 * pixel_phase), 0.10, 0.82)
    ia = np.clip(40.0 + 6.0 * np.cos(time_axis * 0.5 + pixel_phase), 25.0, 55.0)
    ts = (
        294.0
        + 7.0 * np.sin(time_axis - 0.3 * pixel_phase) * pixel_scale
        + 0.6 * rng.standard_normal((nt, npix))
    )
    tau_shape = 0.45 + 0.18 * np.sin(time_axis + pixel_phase)
    tbv = (
        238.0 + 18.0 * tau_shape + 6.0 * sm_ref + 0.8 * rng.standard_normal((nt, npix))
    )
    tbh = (
        228.0 + 14.0 * tau_shape + 4.0 * sm_ref + 0.8 * rng.standard_normal((nt, npix))
    )
    sf = np.clip(0.05 + 0.015 * np.cos(time_axis + pixel_phase), 0.01, 0.10)

    albedo = np.clip(0.08 + 0.02 * rng.standard_normal(npix), 0.03, 0.16)
    b_param = np.clip(0.12 + 0.02 * rng.standard_normal(npix), 0.05, 0.20)
    clay_fraction = np.clip(0.24 + 0.05 * rng.standard_normal(npix), 0.05, 0.45)
    bulk_density = np.clip(1.30 + 0.08 * rng.standard_normal(npix), 1.05, 1.65)
    h_static = np.clip(0.12 + 0.04 * rng.standard_normal(npix), 0.02, 0.35)
    landcover = np.ones(npix, dtype=np.float64)
    ndvi_v_max = np.full(npix, 0.82, dtype=np.float64)
    ndvi_v_min = np.full(npix, 0.10, dtype=np.float64)

    payload: dict[str, object] = {
        "date_keys": _build_date_keys(nt, 4),
        "TBv_mat": tbv.astype(np.float64),
        "TBh_mat": tbh.astype(np.float64),
        "IA_mat": ia.astype(np.float64),
        "Ts_mat": ts.astype(np.float64),
        "SMref_mat": sm_ref.astype(np.float64),
        "NDVI_mat": ndvi.astype(np.float64),
        "SF_mat": sf.astype(np.float64),
        "Albedo": albedo.astype(np.float64),
        "B": b_param.astype(np.float64),
        "CF": clay_fraction.astype(np.float64),
        "BD": bulk_density.astype(np.float64),
        "H": h_static.astype(np.float64),
        "LC": landcover,
        "NDVI_v_max": ndvi_v_max,
        "NDVI_v_min": ndvi_v_min,
        "omega_fixed_vec": np.full(npix, np.nan, dtype=np.float64),
        "h_exp0_vec": np.full(npix, 0.12, dtype=np.float64),
        "alpha_exp0_vec": np.full(npix, 0.1771, dtype=np.float64),
    }
    if dual_temp:
        tc = ts - (1.8 + 0.4 * np.sin(time_axis + 0.2 * pixel_phase))
        tg = ts + (1.5 + 0.4 * np.cos(time_axis - 0.1 * pixel_phase))
        payload["TC_mat"] = tc.astype(np.float64)
        payload["TG_mat"] = tg.astype(np.float64)
    return payload


def _time_call(func, repeats: int) -> tuple[float, object]:
    result = None
    start = perf_counter()
    for _ in range(repeats):
        result = func()
    elapsed = perf_counter() - start
    return elapsed, result


def _measure_trials(func, trials: int, *, warmup: int = 0) -> tuple[np.ndarray, object]:
    result = None
    for _ in range(max(0, warmup)):
        result = func()

    samples = np.empty(max(1, trials), dtype=np.float64)
    for idx in range(samples.size):
        start = perf_counter()
        result = func()
        samples[idx] = perf_counter() - start
    return samples, result


def _measure_timed_trials(
    func, repeats: int, trials: int, *, warmup: int = 0
) -> tuple[np.ndarray, object]:
    result = None
    for _ in range(max(0, warmup)):
        _, result = _time_call(func, repeats)

    samples = np.empty(max(1, trials), dtype=np.float64)
    for idx in range(samples.size):
        elapsed, result = _time_call(func, repeats)
        samples[idx] = elapsed
    return samples, result


def _summarize_samples(samples: np.ndarray) -> dict[str, float]:
    array = np.asarray(samples, dtype=np.float64).reshape(-1)
    return {
        "count": int(array.size),
        "mean_s": round(float(np.mean(array)), 6),
        "std_s": round(float(np.std(array)), 6),
        "min_s": round(float(np.min(array)), 6),
        "max_s": round(float(np.max(array)), 6),
    }


def _sample_pixel_indices(npix: int, sample_count: int) -> np.ndarray:
    sample_count = max(1, min(npix, sample_count))
    return np.linspace(0, npix - 1, sample_count, dtype=np.int64)


def _profile_single_pixel_paths(
    payload: dict[str, object],
    config: OmegaConfig,
    sample_count: int,
    repeats: int,
    trial_count: int,
    warmup: int,
) -> None:
    tbv_mat = np.asarray(payload["TBv_mat"], dtype=np.float64)
    tbh_mat = np.asarray(payload["TBh_mat"], dtype=np.float64)
    ia_mat = np.asarray(payload["IA_mat"], dtype=np.float64)
    ts_mat = np.asarray(payload["Ts_mat"], dtype=np.float64)
    tc_mat = (
        np.asarray(payload["TC_mat"], dtype=np.float64) if "TC_mat" in payload else None
    )
    tg_mat = (
        np.asarray(payload["TG_mat"], dtype=np.float64) if "TG_mat" in payload else None
    )
    smref_mat = np.asarray(payload["SMref_mat"], dtype=np.float64)
    ndvi_mat = np.asarray(payload["NDVI_mat"], dtype=np.float64)
    sf_mat = np.asarray(payload["SF_mat"], dtype=np.float64)
    albedo = np.asarray(payload["Albedo"], dtype=np.float64).reshape(-1)
    b_param = np.asarray(payload["B"], dtype=np.float64).reshape(-1)
    clay_fraction = np.asarray(payload["CF"], dtype=np.float64).reshape(-1)
    bulk_density = np.asarray(payload["BD"], dtype=np.float64).reshape(-1)
    h_static = np.asarray(payload["H"], dtype=np.float64).reshape(-1)
    landcover = np.asarray(payload["LC"], dtype=np.float64).reshape(-1)
    ndvi_v_max = np.asarray(payload["NDVI_v_max"], dtype=np.float64).reshape(-1)
    ndvi_v_min = np.asarray(payload["NDVI_v_min"], dtype=np.float64).reshape(-1)
    fixed_omega = np.asarray(payload["omega_fixed_vec"], dtype=np.float64).reshape(-1)
    exp0_h = np.asarray(payload["h_exp0_vec"], dtype=np.float64).reshape(-1)
    exp0_alpha = np.asarray(payload["alpha_exp0_vec"], dtype=np.float64).reshape(-1)
    date_keys = [
        str(value) for value in np.asarray(payload["date_keys"]).reshape(-1).tolist()
    ]

    blocks, block_start_dates = make_date_blocks(date_keys, config.block_days)
    block_index_arrays = [np.asarray(block, dtype=np.int64) for block in blocks]
    precomputed_blocks = (blocks, block_start_dates, block_index_arrays)
    precomputed_modes = (
        str(config.exp_mode).upper(),
        str(config.temp_scheme).upper() == "DUAL",
    )
    pixel_indices = _sample_pixel_indices(tbv_mat.shape[1], sample_count)

    def _run_once() -> list[dict[str, object]]:
        return [
            retrieve_omega_pixel_timeseries(
                date_keys=date_keys,
                tbv=tbv_mat[:, j],
                tbh=tbh_mat[:, j],
                ts=ts_mat[:, j],
                tc=None if tc_mat is None else tc_mat[:, j],
                tg=None if tg_mat is None else tg_mat[:, j],
                ia=ia_mat[:, j],
                sm_ref=smref_mat[:, j],
                ndvi=ndvi_mat[:, j],
                sf_col=sf_mat[:, j],
                ndvi_max_value=float(ndvi_v_max[j]),
                ndvi_min_value=float(ndvi_v_min[j]),
                albedo_value=float(albedo[j]),
                b_value=float(b_param[j]),
                landcover_value=float(landcover[j]),
                clay_fraction_value=float(clay_fraction[j]),
                bulk_density_value=float(bulk_density[j]),
                h_static_value=float(h_static[j]),
                fixed_omega_value=float(fixed_omega[j])
                if np.isfinite(fixed_omega[j])
                else float("nan"),
                exp0_h_value=float(exp0_h[j]),
                exp0_alpha_value=float(exp0_alpha[j]),
                config=config,
                precomputed_blocks=precomputed_blocks,
                precomputed_modes=precomputed_modes,
            )
            for j in pixel_indices
        ]

    samples, results = _measure_timed_trials(
        _run_once, repeats, trial_count, warmup=warmup
    )
    elapsed = float(samples[-1])
    per_trial_avg_ms = samples * 1000.0 / max(1, repeats * pixel_indices.size)
    print(
        "single_pixel_solver:",
        {
            "sample_count": int(pixel_indices.size),
            "repeats": repeats,
            "trial_count": int(max(1, trial_count)),
            "warmup": int(max(0, warmup)),
            "last_total_s": round(elapsed, 6),
            "avg_ms_per_pixel": round(float(np.mean(per_trial_avg_ms)), 3),
            "std_ms_per_pixel": round(float(np.std(per_trial_avg_ms)), 3),
            "min_ms_per_pixel": round(float(np.min(per_trial_avg_ms)), 3),
            "max_ms_per_pixel": round(float(np.max(per_trial_avg_ms)), 3),
            "trial_summary": _summarize_samples(samples),
            "mean_n_use": round(
                float(
                    np.nanmean(
                        [
                            np.asarray(item["n_use"], dtype=np.float64)
                            for item in results
                        ]
                    )
                ),
                3,
            ),
        },
    )


def _profile_execute_omega_retrieval(
    payload: dict[str, object],
    config: OmegaConfig,
    repeats: int,
    trial_count: int,
    warmup: int,
) -> None:
    samples, result = _measure_timed_trials(
        lambda: execute_omega_retrieval(payload, config=config),
        repeats,
        trial_count,
        warmup=warmup,
    )
    elapsed = float(samples[-1])
    omega_mat = np.asarray(result["OMEGA_mat"], dtype=np.float64)
    per_trial_avg_ms = samples * 1000.0 / max(1, repeats)
    print(
        "execute_omega_retrieval:",
        {
            "repeats": repeats,
            "trial_count": int(max(1, trial_count)),
            "warmup": int(max(0, warmup)),
            "last_total_s": round(elapsed, 6),
            "avg_ms": round(float(np.mean(per_trial_avg_ms)), 3),
            "std_ms": round(float(np.std(per_trial_avg_ms)), 3),
            "min_ms": round(float(np.min(per_trial_avg_ms)), 3),
            "max_ms": round(float(np.max(per_trial_avg_ms)), 3),
            "trial_summary": _summarize_samples(samples),
            "shape": tuple(int(v) for v in omega_mat.shape),
            "finite_ratio": round(float(np.mean(np.isfinite(omega_mat))), 4),
        },
    )


def _run_cprofile(
    payload: dict[str, object], config: OmegaConfig, sort_by: str, top_n: int
) -> None:
    profiler = cProfile.Profile()
    profiler.enable()
    execute_omega_retrieval(payload, config=config)
    profiler.disable()
    print(f"cProfile top {top_n} by {sort_by}:")
    stats = pstats.Stats(profiler).strip_dirs().sort_stats(sort_by)
    stats.print_stats(top_n)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Profile omega retrieval with synthetic but realistic timeseries shapes."
    )
    parser.add_argument("--nt", type=int, default=64, help="Number of timesteps.")
    parser.add_argument("--npix", type=int, default=192, help="Number of pixels.")
    parser.add_argument(
        "--repeats", type=int, default=3, help="Full retrieval repeats."
    )
    parser.add_argument(
        "--pixel-repeats", type=int, default=4, help="Single-pixel solver repeats."
    )
    parser.add_argument(
        "--pixel-samples",
        type=int,
        default=8,
        help="Number of sampled pixels for solver timing.",
    )
    parser.add_argument(
        "--trial-count",
        type=int,
        default=5,
        help="Number of repeated timing trials for each profile section.",
    )
    parser.add_argument(
        "--warmup", type=int, default=1, help="Warmup runs before timing trials."
    )
    parser.add_argument("--block-days", type=int, default=8, help="Block size in days.")
    parser.add_argument(
        "--temp-scheme",
        choices=("ORIG_TS", "DUAL"),
        default="ORIG_TS",
        help="Temperature scheme.",
    )
    parser.add_argument(
        "--exp-mode",
        choices=("Exp0", "Exp1A", "Exp1B", "Exp2"),
        default="Exp2",
        help="Experiment mode.",
    )
    parser.add_argument(
        "--lambda-list",
        type=str,
        default="1,10,100,1000",
        help="Comma-separated lambda candidates.",
    )
    parser.add_argument("--seed", type=int, default=7, help="Random seed.")
    parser.add_argument(
        "--cprofile",
        action="store_true",
        help="Run cProfile for one execute_omega_retrieval call.",
    )
    parser.add_argument("--cprofile-sort", default="tottime", help="cProfile sort key.")
    parser.add_argument(
        "--cprofile-top",
        type=int,
        default=20,
        help="Number of cProfile entries to print.",
    )
    args = parser.parse_args()

    dual_temp = args.temp_scheme.upper() == "DUAL"
    payload = _build_payload(args.nt, args.npix, dual_temp=dual_temp, seed=args.seed)
    lambda_list = tuple(
        float(item.strip()) for item in args.lambda_list.split(",") if item.strip()
    )
    config = replace(
        OmegaConfig(),
        temp_scheme=args.temp_scheme,
        exp_mode=args.exp_mode,
        block_days=int(args.block_days),
        lambda_list=lambda_list,
    )

    print(
        "omega_profile_config:",
        {
            "nt": args.nt,
            "npix": args.npix,
            "temp_scheme": config.temp_scheme,
            "exp_mode": config.exp_mode,
            "block_days": config.block_days,
            "lambda_list": config.lambda_list,
            "seed": args.seed,
        },
    )

    _profile_single_pixel_paths(
        payload,
        config,
        args.pixel_samples,
        args.pixel_repeats,
        args.trial_count,
        args.warmup,
    )
    _profile_execute_omega_retrieval(
        payload, config, args.repeats, args.trial_count, args.warmup
    )
    if args.cprofile:
        _run_cprofile(payload, config, args.cprofile_sort, args.cprofile_top)


if __name__ == "__main__":
    main()
