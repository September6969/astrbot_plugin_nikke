"""Face-guided whole-character centering for NIKKE Character Card artwork.

This module provides an opt-in preview pass for a second stage after the existing
Spine face/eye anchor:

    Spine face / eye anchor
        -> existing face-first scale + translate
        -> face-guided alpha body-axis analysis (this module)
        -> bounded horizontal centering correction

Revision v5 incorporates four Astra review rounds.  In addition to the v2/v3 fixes, it
keeps the following invariants before any production opt-in:

* a long connected accessory must never accumulate clipped per-row drift;
* transparent canvas padding must not change the result;
* a long fully-transparent vertical gap must terminate the current subject path.

The v2 detached-weapon and symmetric-fork guarantees remain in force.

The face anchor remains the hard constraint.  Body centering is a soft,
confidence-gated correction.  Scale never changes.  Runtime Spine parsing,
OpenCV and ML are not required; Pillow is sufficient.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Protocol, Sequence


class AlphaPixels(Protocol):
    """可按像素坐标读取透明度的视图。"""

    def __getitem__(self, point: tuple[int, int]) -> int: ...


class AlphaChannel(Protocol):
    """RGBA 图像的透明度通道。"""

    @property
    def size(self) -> tuple[int, int]: ...

    def load(self) -> AlphaPixels: ...


class RasterImage(Protocol):
    """图像算法实际使用的最小结构化接口。"""

    @property
    def width(self) -> int: ...

    @property
    def height(self) -> int: ...

    def convert(self, mode: str) -> RasterImage: ...

    def getchannel(self, channel: str) -> AlphaChannel: ...


@dataclass(frozen=True)
class FrameTransform:
    """Numeric transform produced by the existing face-anchor stage.

    ``scale`` maps source portrait pixels to final Character Card pixels.
    ``left`` / ``top`` are the final-card offsets of the scaled portrait.
    """

    scale: float
    left: float
    top: float


@dataclass(frozen=True)
class CenteringConfig:
    """Policy for the opt-in face-guided body-centering pass.

    Phase 1 intentionally enables **horizontal correction only**.  The old
    vertical estimate was just the alpha silhouette's top/bottom midpoint and
    was too sensitive to hair, skirts and weapons.  ``vertical_gain`` therefore
    defaults to ``0`` until real-art regressions prove a benefit.
    """

    canvas_width: float = 1600.0
    canvas_height: float = 2400.0
    body_target_x: float = 800.0
    body_target_y: float = 855.0  # diagnostic / future phase only

    # Ignore near-transparent glow / antialiasing dust.
    alpha_threshold: int = 24
    trim_fraction: float = 0.015

    # Row-run extraction.
    max_run_gap: int = 2
    min_run_width: int = 2
    max_row_samples: int = 360
    min_row_samples: int = 12

    # Local subject-scale bootstrap.  Never derive this from canvas width/height:
    # transparent export padding must be a pure coordinate translation.
    bootstrap_band_ratio: float = 0.18
    bootstrap_min_rows: int = 3
    # v5 bootstrap is deliberately face-local and progressive.  The initial
    # trusted scale is built from rows nearest the face anchor.  A one-sided
    # expansion is never trusted merely because its *total* width stays below a
    # large-ratio cutoff: left/right half-width balance is checked explicitly.
    # If the seed has no sufficiently balanced face/neck evidence, phase 1 fails
    # closed and preserves the existing face-anchor composition.
    bootstrap_seed_rows: int = 7
    bootstrap_core_expansion: float = 2.25
    bootstrap_min_half_balance: float = 0.48
    bootstrap_min_clean_rows: int = 3
    bootstrap_min_clean_fraction: float = 0.20
    bootstrap_max_cluster_ratio: float = 1.85
    bootstrap_max_bad_rows: int = 2

    # Tracking continuity.  The lateral jump gate is normalised by the current
    # trusted body width, with a tiny absolute floor for very small portraits.
    max_lateral_jump_ratio: float = 0.85
    min_lateral_jump_px: float = 4.0
    max_tracking_misses: int = 3

    # Fully transparent vertical holes are allowed only while they are short at
    # the current subject scale.  A long gap means the tracked subject ended.
    max_vertical_gap_ratio: float = 2.0
    min_vertical_gap_px: float = 8.0

    # A single alpha run that suddenly becomes much wider is commonly a torso
    # touching a rifle / cape.  Its midpoint is not accepted at face value.
    max_width_growth_ratio: float = 1.75
    max_axis_step_ratio: float = 0.32
    trusted_width_update: float = 0.10

    # Abnormally-wide connected runs are *held*, not followed.  If the tracker
    # cannot reacquire an ordinary body-width observation within this scale-
    # normalised vertical span, terminate rather than accumulating drift.
    max_untrusted_span_ratio: float = 2.75

    # Symmetric branch handling (typically two legs).  Opposite-side candidates
    # with comparable distance/width are represented by their shared midline.
    symmetric_distance_tolerance: float = 0.35
    symmetric_min_width_ratio: float = 0.45
    symmetric_max_span_ratio: float = 3.5

    # Upper / middle body rows carry more weight than far-lower rows.  This is a
    # weighting rule only; it does not crop the legs from analysis.
    torso_priority_fraction: float = 0.60
    lower_body_weight: float = 0.65

    # Phase 1 uses only the tracked axis by default.  Keeping this configurable
    # permits preview experiments, but lowering it reintroduces bbox sensitivity.
    body_axis_weight: float = 1.0

    # Correction policy.
    horizontal_gain: float = 0.72
    vertical_gain: float = 0.0
    min_confidence_for_shift: float = 0.45
    max_shift_x: float = 140.0
    max_shift_y: float = 72.0

    # Final-card face safety box.
    face_safe_left: float = 520.0
    face_safe_top: float = 360.0
    face_safe_right: float = 1080.0
    face_safe_bottom: float = 720.0


DEFAULT_CENTERING_CONFIG = CenteringConfig()


@dataclass(frozen=True)
class SilhouetteAnalysis:
    """Diagnostics produced from the portrait alpha channel."""

    robust_bounds: tuple[int, int, int, int]  # left, top, right, bottom
    body_axis_x: float
    visual_center_x: float
    visual_center_y: float  # diagnostic only while vertical_gain == 0
    alpha_pixels: int
    row_samples: int
    confidence: float
    path_coverage: float
    path_continuity: float
    path_ambiguity: float
    width_reliability: float
    terminated_early: bool
    trusted_width: float
    bootstrap_width: float
    bootstrap_reliable: bool
    bootstrap_support_rows: int
    bootstrap_contaminated_rows: int
    bootstrap_clean_rows: int
    bootstrap_clean_fraction: float
    bootstrap_half_balance: float
    max_vertical_gap: float
    max_untrusted_span: float


@dataclass(frozen=True)
class CenteringResult:
    """Candidate transform plus diagnostics for review / preview tooling."""

    transform: FrameTransform
    analysis: SilhouetteAnalysis | None
    face_before: tuple[float, float]
    face_after: tuple[float, float]
    body_before: tuple[float, float] | None
    body_after: tuple[float, float] | None
    raw_shift: tuple[float, float]
    applied_shift: tuple[float, float]
    clamped: bool
    reason: str


@dataclass(frozen=True)
class _BootstrapEstimate:
    """Conservative subject-scale estimate established next to the face anchor.

    ``width`` is a body-scale prior, not a literal silhouette width.  One-sided
    growth is represented by the face-centred symmetric core, but that core is
    only a *tentative* scale.  Reliability additionally requires independent
    balanced face/neck rows, so a medium shoulder-attached prop cannot become a
    trusted prior just because its width is stable.
    """

    width: float
    reliable: bool
    support_rows: int
    contaminated_rows: int
    cluster_ratio: float
    clean_rows: int
    clean_fraction: float
    half_balance: float


@dataclass(frozen=True)
class _Observation:
    """One row observation used by the axis tracker.

    ``raw_axis_x`` is the geometry's unmodified midpoint estimate and is used for
    continuity scoring.  ``axis_x`` is the conservative estimate allowed to
    contribute to centering.  ``trusted_axis`` controls whether the observation
    may update the persistent tracker state.
    """

    axis_x: float
    raw_axis_x: float
    run_width: float
    ambiguity_quality: float
    width_quality: float
    symmetric_branch: bool
    trusted_axis: bool


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def center_after_face_anchor(
    portrait: RasterImage,
    *,
    face_point: Sequence[float],
    base: FrameTransform,
    config: CenteringConfig = DEFAULT_CENTERING_CONFIG,
) -> CenteringResult:
    """Propose a conservative second-stage correction after face anchoring.

    The function is deterministic and side-effect free.  It returns a no-op if
    alpha evidence is insufficient or tracking confidence is below the configured
    threshold.  The candidate never changes scale.
    """

    _validate_inputs(portrait, face_point, base, config)
    fx, fy = float(face_point[0]), float(face_point[1])
    face_before = (base.left + fx * base.scale, base.top + fy * base.scale)

    analysis = analyze_face_guided_silhouette(
        portrait,
        face_point=(fx, fy),
        config=config,
    )
    if analysis is None:
        return _noop_result(base, face_before, reason="insufficient_silhouette")

    body_before = (
        base.left + analysis.visual_center_x * base.scale,
        base.top + analysis.visual_center_y * base.scale,
    )
    raw_dx = config.body_target_x - body_before[0]
    raw_dy = config.body_target_y - body_before[1]

    # A low-confidence path is diagnostic-only.  Do not allow a questionable
    # silhouette interpretation to modify a face-calibrated production frame.
    if analysis.confidence < config.min_confidence_for_shift:
        return CenteringResult(
            transform=base,
            analysis=analysis,
            face_before=face_before,
            face_after=face_before,
            body_before=body_before,
            body_after=body_before,
            raw_shift=(raw_dx, raw_dy),
            applied_shift=(0.0, 0.0),
            clamped=False,
            reason="low_confidence",
        )

    wanted_dx = raw_dx * config.horizontal_gain
    wanted_dy = raw_dy * config.vertical_gain

    dx_lo, dx_hi = _safe_delta_bounds(
        face_before[0], config.face_safe_left, config.face_safe_right, config.max_shift_x
    )
    dy_lo, dy_hi = _safe_delta_bounds(
        face_before[1], config.face_safe_top, config.face_safe_bottom, config.max_shift_y
    )

    bounded_dx = _clamp(wanted_dx, dx_lo, dx_hi)
    bounded_dy = _clamp(wanted_dy, dy_lo, dy_hi)
    clamped = (
        not math.isclose(bounded_dx, wanted_dx, abs_tol=1e-6)
        or not math.isclose(bounded_dy, wanted_dy, abs_tol=1e-6)
    )

    # Confidence now represents path continuity / ambiguity / width reliability,
    # not merely the number of sampled rows.  Let it directly damp the proposal.
    applied_dx = bounded_dx * analysis.confidence
    applied_dy = bounded_dy * analysis.confidence

    transform = FrameTransform(
        scale=base.scale,
        left=base.left + applied_dx,
        top=base.top + applied_dy,
    )
    face_after = (face_before[0] + applied_dx, face_before[1] + applied_dy)
    body_after = (body_before[0] + applied_dx, body_before[1] + applied_dy)

    return CenteringResult(
        transform=transform,
        analysis=analysis,
        face_before=face_before,
        face_after=face_after,
        body_before=body_before,
        body_after=body_after,
        raw_shift=(raw_dx, raw_dy),
        applied_shift=(applied_dx, applied_dy),
        clamped=clamped,
        reason="ok",
    )


def _alpha_histograms(portrait: RasterImage, threshold: int):
    """生成阈值化透明度在横纵轴上的投影。"""
    alpha = portrait.convert("RGBA").getchannel("A")
    width, height = alpha.size
    pixels = alpha.load()
    x_hist = [0] * width
    y_hist = [0] * height
    alpha_pixels = 0
    for y in range(height):
        row_count = 0
        for x in range(width):
            if pixels[x, y] >= threshold:
                x_hist[x] += 1
                row_count += 1
        y_hist[y] = row_count
        alpha_pixels += row_count
    return pixels, width, height, x_hist, y_hist, alpha_pixels


def _robust_alpha_bounds_from_histograms(
    x_hist: Sequence[int], y_hist: Sequence[int], trim_fraction: float
) -> tuple[int, int, int, int] | None:
    left = _hist_quantile_index(x_hist, trim_fraction)
    right = _hist_quantile_index(x_hist, 1.0 - trim_fraction)
    top = _hist_quantile_index(y_hist, trim_fraction)
    bottom = _hist_quantile_index(y_hist, 1.0 - trim_fraction)
    if None in (left, right, top, bottom):
        return None
    assert left is not None and right is not None and top is not None and bottom is not None
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def robust_alpha_bounds(
    portrait: RasterImage,
    *,
    alpha_threshold: int = 24,
    trim_fraction: float = 0.015,
) -> tuple[int, int, int, int] | None:
    """返回忽略少量透明度离群像素后的角色轮廓边界。"""
    if type(alpha_threshold) is not int or not 0 <= alpha_threshold <= 255:
        raise ValueError("alpha_threshold must be an integer in [0, 255]")
    if (
        not isinstance(trim_fraction, (int, float))
        or isinstance(trim_fraction, bool)
        or not math.isfinite(trim_fraction)
        or not 0.0 <= trim_fraction < 0.5
    ):
        raise ValueError("trim_fraction must be finite and in [0, 0.5)")
    _, _, _, x_hist, y_hist, alpha_pixels = _alpha_histograms(
        portrait, alpha_threshold
    )
    if alpha_pixels == 0:
        return None
    return _robust_alpha_bounds_from_histograms(x_hist, y_hist, float(trim_fraction))


def analyze_face_guided_silhouette(
    portrait: RasterImage,
    *,
    face_point: Sequence[float],
    config: CenteringConfig = DEFAULT_CENTERING_CONFIG,
) -> SilhouetteAnalysis | None:
    """Estimate a conservative body axis from the alpha silhouette.

    v3 deliberately separates *trusted state* from *raw observation*:

    * ordinary head / neck / torso-width rows may update the persistent axis;
    * abnormally-wide connected rows may contribute only a held-axis sample and
      never feed their shifted midpoint back into the tracker;
    * long untrusted spans terminate instead of accumulating many small clips;
    * transparent rows count as missing support and a long scale-normalised
      vertical gap terminates the current subject path;
    * bootstrap scale comes from a face-centred core and progressive trust gate, never canvas dimensions.

    These rules make the proposal invariant to transparent export padding and
    intentionally biased toward "keep the face-calibrated frame" when anatomy is
    ambiguous.  Phase 1 remains horizontal-only by default.
    """

    fx, fy = float(face_point[0]), float(face_point[1])
    threshold = config.alpha_threshold
    pixels, width, height, x_hist, y_hist, alpha_pixels = _alpha_histograms(
        portrait, threshold
    )

    if alpha_pixels < max(64, config.min_row_samples * config.min_run_width):
        return None

    bounds = _robust_alpha_bounds_from_histograms(
        x_hist, y_hist, config.trim_fraction
    )
    if bounds is None:
        return None
    left, top, right, bottom = bounds

    active_height = max(1, bottom - top + 1)
    # Padding-invariant: this offset is based on opaque-subject height, not the
    # exported image canvas height.
    sample_top = max(top, int(round(fy - active_height * 0.03)))
    sample_bottom = bottom
    span = max(1, sample_bottom - sample_top + 1)
    row_step = max(1, math.ceil(span / max(1, config.max_row_samples)))

    tracking_x = _clamp(fx, 0.0, float(width - 1))
    bootstrap = _bootstrap_subject_width(
        pixels,
        width=width,
        top=top,
        bottom=bottom,
        face_x=tracking_x,
        face_y=fy,
        threshold=threshold,
        config=config,
    )
    if bootstrap is None:
        # No trustworthy face-local scale means the second-stage centering pass
        # must not invent one from the global silhouette.  The caller will keep
        # the already face-calibrated composition unchanged.
        return None
    bootstrap_width = bootstrap.width
    trusted_width = max(float(config.min_run_width * 2), float(bootstrap_width))

    centers: list[float] = []
    weights: list[float] = []
    continuity_scores: list[float] = []
    ambiguity_scores: list[float] = []
    width_scores: list[float] = []

    misses = 0
    scanned = 0
    accepted = 0
    terminated_early = False
    first_accepted_y: int | None = None
    last_accepted_y: int | None = None
    supported_vertical_px = 0.0

    vertical_gap_px = 0.0
    max_vertical_gap_seen = 0.0
    untrusted_span_px = 0.0
    max_untrusted_span_seen = 0.0

    torso_cut_y = sample_top + span * config.torso_priority_fraction

    for y in range(sample_top, sample_bottom + 1, row_step):
        scanned += 1
        runs = _opaque_runs_for_row(
            pixels,
            y,
            width,
            threshold=threshold,
            max_gap=config.max_run_gap,
            min_width=config.min_run_width,
        )

        allowed_vertical_gap = max(
            config.min_vertical_gap_px,
            trusted_width * config.max_vertical_gap_ratio,
        )
        if not runs:
            vertical_gap_px += row_step
            max_vertical_gap_seen = max(max_vertical_gap_seen, vertical_gap_px)
            # Unlike v2, empty rows are evidence.  A short alpha hole may be
            # crossed, but a long gap ends the subject path before a lower prop
            # or detached ornament can become the new body.
            if vertical_gap_px > allowed_vertical_gap:
                terminated_early = y < sample_bottom
                break
            continue

        # A short transparent hole is tolerated, but it remains represented in
        # coverage because ``scanned`` includes those rows.
        vertical_gap_px = 0.0

        previous_x = tracking_x
        gate = max(config.min_lateral_jump_px, trusted_width * config.max_lateral_jump_ratio)
        candidates = [
            run for run in runs
            if _distance_to_interval(tracking_x, run[0], run[1]) <= gate
        ]

        if not candidates:
            misses += 1
            if misses > config.max_tracking_misses:
                terminated_early = y < sample_bottom
                break
            continue

        observation = _choose_axis_observation(
            candidates,
            tracking_x=tracking_x,
            trusted_width=trusted_width,
            gate=gate,
            config=config,
        )
        if observation is None:
            misses += 1
            if misses > config.max_tracking_misses:
                terminated_early = y < sample_bottom
                break
            continue

        misses = 0

        # IMPORTANT: continuity is scored against the *raw* geometry, not the
        # clipped / held estimate.  This prevents smoothing from laundering a
        # persistently wrong connected-accessory midpoint into a high score.
        raw_normalised_step = abs(observation.raw_axis_x - previous_x) / max(gate, 1e-6)
        continuity = _clamp(1.0 - raw_normalised_step, 0.0, 1.0)

        if observation.trusted_axis:
            untrusted_span_px = 0.0
            # Only trusted observations may change the persistent axis.
            tracking_x = previous_x * 0.68 + observation.axis_x * 0.32
        else:
            # Hold the last trusted axis.  There is deliberately no cumulative
            # clipped drift across a connected rifle / cape / giant accessory.
            tracking_x = previous_x
            untrusted_span_px += row_step
            max_untrusted_span_seen = max(max_untrusted_span_seen, untrusted_span_px)
            allowed_untrusted_span = max(
                float(row_step * 2),
                trusted_width * config.max_untrusted_span_ratio,
            )
            if untrusted_span_px > allowed_untrusted_span:
                terminated_early = y < sample_bottom
                break

        accepted += 1
        supported_vertical_px += row_step
        if first_accepted_y is None:
            first_accepted_y = y
        last_accepted_y = y

        vertical_weight = 1.0 if y <= torso_cut_y else config.lower_body_weight
        sample_weight = (
            min(observation.run_width, trusted_width * 1.35)
            * vertical_weight
            * observation.width_quality
            * observation.ambiguity_quality
        )
        centers.append(observation.axis_x)
        weights.append(max(sample_weight, 1e-6))
        continuity_scores.append(continuity)
        ambiguity_scores.append(observation.ambiguity_quality)
        width_scores.append(observation.width_quality)

        # Only ordinary, trusted body-width rows may redefine subject scale.
        if observation.trusted_axis:
            growth = observation.run_width / max(trusted_width, 1e-6)
            if 0.55 <= growth <= config.max_width_growth_ratio:
                rate = config.trusted_width_update
                trusted_width = trusted_width * (1.0 - rate) + observation.run_width * rate

    if len(centers) < config.min_row_samples:
        return None

    body_axis_x = _weighted_median(centers, weights)
    bbox_center_x = (left + right) / 2.0
    visual_center_x = (
        body_axis_x * config.body_axis_weight
        + bbox_center_x * (1.0 - config.body_axis_weight)
    )
    visual_center_y = (top + bottom) / 2.0

    sample_score = _clamp(
        len(centers) / float(max(1, config.min_row_samples * 3)), 0.0, 1.0
    )
    # v3 coverage includes transparent rows and lateral misses.  A 100px empty
    # gap can no longer yield path_coverage == 1.0.
    path_coverage = accepted / float(max(1, scanned))
    path_continuity = _mean(continuity_scores, default=0.0)
    path_ambiguity = _mean(ambiguity_scores, default=0.0)
    width_reliability = _mean(width_scores, default=0.0)

    # Effective span is actual supported scan height, not first..last including
    # empty space between two disconnected objects.
    span_score = _clamp(supported_vertical_px / max(1.0, span * 0.45), 0.0, 1.0)

    confidence = sample_score
    confidence *= 0.30 + 0.70 * path_coverage
    confidence *= 0.35 + 0.65 * path_continuity
    confidence *= 0.40 + 0.60 * path_ambiguity
    confidence *= 0.35 + 0.65 * width_reliability
    confidence *= 0.50 + 0.50 * span_score

    # Explicitly penalise evidence that ended in a long untrusted connected run
    # or a long transparent gap, even if the earlier torso path was excellent.
    if max_untrusted_span_seen > trusted_width:
        confidence *= 0.82
    if max_vertical_gap_seen > max(config.min_vertical_gap_px, trusted_width):
        confidence *= 0.88
    # v4: an ambiguous bootstrap can still be returned for diagnostics, but it
    # is never allowed to look production-worthy.  With the default threshold
    # this forces a no-op and preserves the face-anchor composition.
    if not bootstrap.reliable:
        confidence *= 0.20
    confidence = _clamp(confidence, 0.0, 1.0)

    return SilhouetteAnalysis(
        robust_bounds=(left, top, right, bottom),
        body_axis_x=body_axis_x,
        visual_center_x=visual_center_x,
        visual_center_y=visual_center_y,
        alpha_pixels=alpha_pixels,
        row_samples=len(centers),
        confidence=confidence,
        path_coverage=path_coverage,
        path_continuity=path_continuity,
        path_ambiguity=path_ambiguity,
        width_reliability=width_reliability,
        terminated_early=terminated_early,
        trusted_width=trusted_width,
        bootstrap_width=float(bootstrap_width),
        bootstrap_reliable=bootstrap.reliable,
        bootstrap_support_rows=bootstrap.support_rows,
        bootstrap_contaminated_rows=bootstrap.contaminated_rows,
        bootstrap_clean_rows=bootstrap.clean_rows,
        bootstrap_clean_fraction=bootstrap.clean_fraction,
        bootstrap_half_balance=bootstrap.half_balance,
        max_vertical_gap=max_vertical_gap_seen,
        max_untrusted_span=max_untrusted_span_seen,
    )


def css_style_for_transform(portrait: RasterImage, transform: FrameTransform) -> str:
    """Serialise a candidate transform in the same shape as ``framing()``."""

    width = portrait.width * transform.scale
    height = portrait.height * transform.scale
    return (
        f"width:{width:.3f}px;height:{height:.3f}px;"
        f"left:{transform.left:.3f}px;top:{transform.top:.3f}px;"
        "object-fit:contain"
    )


# ---------------------------------------------------------------------------
# Tracking helpers
# ---------------------------------------------------------------------------


def _bootstrap_subject_width(
    pixels,
    *,
    width: int,
    top: int,
    bottom: int,
    face_x: float,
    face_y: float,
    threshold: int,
    config: CenteringConfig,
) -> _BootstrapEstimate | None:
    """Build a trusted local subject scale without accepting shoulder props.

    v3 used the median width of a whole face/upper-torso band.  That is padding
    invariant, but it can still be poisoned when a connected accessory begins
    early enough to occupy most rows in the band.

    v5 uses four protections:

    1. **face-centred core** -- for a run containing ``face_x`` we measure the
       symmetric core around the face axis.  One-sided growth therefore cannot
       inflate the tentative scale merely by extending one edge of the run;
    2. **half-width balance evidence** -- a seed row is independently trusted
       only when its left and right radii around ``face_x`` are sufficiently
       balanced.  This catches medium one-sided attachments that are too small
       for the old ``full/core`` expansion cutoff;
    3. **nearest-first seed** -- only rows closest to the known face anchor
       establish the initial scale.  Wider lower rows must pass a growth gate;
    4. **fail-closed bootstrap** -- if the local width groups disagree, or if the
       seed lacks enough balanced face/neck evidence, the estimate is explicitly
       unreliable.  The public centering function then preserves the existing
       face-anchor composition through the confidence gate.

    The helper intentionally ignores global canvas dimensions and global alpha
    bounds as a scale source.  Transparent export padding is thus irrelevant.
    """

    active_height = max(1, bottom - top + 1)
    band = max(config.bootstrap_seed_rows + 2, int(round(active_height * config.bootstrap_band_ratio)))
    # Include a tiny amount above the face to survive small transparent eye/face
    # holes, but make the scan primarily downward toward neck/torso.
    y0 = max(top, int(round(face_y - max(2.0, active_height * 0.015))))
    y1 = min(bottom, int(round(face_y + band)))

    rows: list[tuple[float, float, float, bool, float]] = []
    # (distance from face_y, effective width, full width, contaminated, half_balance)
    for y in range(y0, y1 + 1):
        runs = _opaque_runs_for_row(
            pixels,
            y,
            width,
            threshold=threshold,
            max_gap=config.max_run_gap,
            min_width=config.min_run_width,
        )
        if not runs:
            continue

        containing = [run for run in runs if run[0] <= face_x <= run[1]]
        if not containing:
            # Bootstrap is intentionally stricter than body tracking.  A row not
            # touching the known face axis cannot establish subject scale.
            continue

        # Opaque runs cannot normally overlap, but choose the narrowest if a
        # future extractor changes that assumption.  Narrowest is the safer
        # body-scale prior in the presence of merged decorations.
        run = min(containing, key=_run_width)
        full_width = float(_run_width(run))
        left_radius = max(0.0, face_x - run[0] + 0.5)
        right_radius = max(0.0, run[1] - face_x + 0.5)
        larger_radius = max(left_radius, right_radius, 1e-6)
        half_balance = min(left_radius, right_radius) / larger_radius
        core_width = max(
            float(config.min_run_width * 2),
            2.0 * min(left_radius, right_radius),
        )

        # ``bootstrap_core_expansion`` still catches extreme growth, but v5 does
        # not rely on that single cutoff.  Medium one-sided growth is also treated
        # as uncertain when the two half-widths disagree strongly.  We use the
        # symmetric core only as a *tentative* width and separately remember that
        # this row cannot prove the seed is anatomical.
        core_cap = core_width * config.bootstrap_core_expansion
        extreme_growth = full_width > core_cap + 1e-6
        asymmetric = half_balance < config.bootstrap_min_half_balance
        contaminated = extreme_growth or asymmetric
        effective_width = core_width if contaminated else full_width
        rows.append(
            (abs(y - face_y), effective_width, full_width, contaminated, half_balance)
        )

    if len(rows) < config.bootstrap_min_rows:
        return None

    rows.sort(key=lambda item: item[0])
    seed_rows = rows[: max(config.bootstrap_min_rows, config.bootstrap_seed_rows)]

    # A stable symmetric core by itself is not enough: an attached prop can make
    # every nearby row consistently asymmetric.  Require independent balanced
    # face/neck rows before granting production-level bootstrap reliability.
    # Do not require the *nearest* rows to be balanced: an eye/face attachment
    # anchor may legitimately sit off the alpha midpoint in a profile or tilted
    # pose.  Instead search the whole small bootstrap band for independent
    # balanced face/neck evidence, then use the nearest such rows as the seed.
    # This is deliberately different from simply lowering the old 2.25 ratio.
    clean_band_rows = [row for row in rows if not row[3]]
    clean_seed_rows = clean_band_rows[: max(config.bootstrap_min_clean_rows, config.bootstrap_seed_rows)]
    clean_rows = len(clean_band_rows)
    clean_fraction = clean_rows / float(max(1, len(rows)))
    half_balance = _median([row[4] for row in rows])

    # When clean evidence exists, it owns the seed.  Otherwise keep the symmetric
    # cores only for diagnostics/tracking scale, but mark the bootstrap unreliable
    # so the default pass remains a no-op.
    seed_source = clean_seed_rows if len(clean_seed_rows) >= config.bootstrap_min_clean_rows else seed_rows
    seed_widths = [row[1] for row in seed_source]
    seed_width = _median(seed_widths)
    seed_min = min(seed_widths)
    seed_max = max(seed_widths)
    cluster_ratio = seed_max / max(seed_min, 1e-6)

    reliable = (
        cluster_ratio <= config.bootstrap_max_cluster_ratio
        and clean_rows >= config.bootstrap_min_clean_rows
        and clean_fraction >= config.bootstrap_min_clean_fraction
    )

    accepted_widths: list[float] = []
    contaminated_rows = 0
    consecutive_bad = 0
    lower = seed_width / config.max_width_growth_ratio
    upper = seed_width * config.max_width_growth_ratio

    for _, effective_width, full_width, contaminated, _ in rows:
        if contaminated:
            contaminated_rows += 1
            # A row already rejected by the independent half-width/expansion
            # evidence cannot contradict a later clean seed.  In particular, a
            # legitimate off-centre face may have several asymmetric head rows
            # before balanced neck/torso rows appear.  Skip it rather than letting
            # those rows exhaust ``bootstrap_max_bad_rows``.
            continue
        if lower <= effective_width <= upper:
            accepted_widths.append(effective_width)
            consecutive_bad = 0
        else:
            consecutive_bad += 1
            # A sustained *clean* width jump during bootstrap is evidence that the
            # band has reached a different anatomical/attachment scale.  Stop
            # before it can redefine the trusted seed.
            if consecutive_bad > config.bootstrap_max_bad_rows:
                break

    if len(accepted_widths) < config.bootstrap_min_rows:
        return _BootstrapEstimate(
            width=max(float(config.min_run_width * 2), seed_width),
            reliable=False,
            support_rows=len(accepted_widths),
            contaminated_rows=contaminated_rows,
            cluster_ratio=cluster_ratio,
            clean_rows=clean_rows,
            clean_fraction=clean_fraction,
            half_balance=half_balance,
        )

    trusted = _median(accepted_widths)
    return _BootstrapEstimate(
        width=max(float(config.min_run_width * 2), trusted),
        reliable=reliable,
        support_rows=len(accepted_widths),
        contaminated_rows=contaminated_rows,
        cluster_ratio=cluster_ratio,
        clean_rows=clean_rows,
        clean_fraction=clean_fraction,
        half_balance=half_balance,
    )


def _choose_axis_observation(
    candidates: Sequence[tuple[int, int]],
    *,
    tracking_x: float,
    trusted_width: float,
    gate: float,
    config: CenteringConfig,
) -> _Observation | None:
    """Choose a mirror-stable observation without allowing cumulative prop drift."""

    if not candidates:
        return None

    # First look for a plausible left/right branch pair around the previous
    # axis.  This removes scan-order bias on symmetric legs.
    left_runs = [r for r in candidates if _run_mid(r) < tracking_x]
    right_runs = [r for r in candidates if _run_mid(r) > tracking_x]
    if left_runs and right_runs:
        left = min(left_runs, key=lambda r: abs(_run_mid(r) - tracking_x))
        right = min(right_runs, key=lambda r: abs(_run_mid(r) - tracking_x))
        dl = abs(_run_mid(left) - tracking_x)
        dr = abs(_run_mid(right) - tracking_x)
        wl = _run_width(left)
        wr = _run_width(right)
        distance_ok = abs(dl - dr) <= max(
            config.min_lateral_jump_px,
            trusted_width * config.symmetric_distance_tolerance,
        )
        width_ratio = min(wl, wr) / max(float(max(wl, wr)), 1.0)
        span_ratio = (right[1] - left[0] + 1) / max(trusted_width, 1.0)
        if (
            distance_ok
            and width_ratio >= config.symmetric_min_width_ratio
            and span_ratio <= config.symmetric_max_span_ratio
        ):
            shared_mid = (_run_mid(left) + _run_mid(right)) / 2.0
            max_step = max(config.min_lateral_jump_px, trusted_width * config.max_axis_step_ratio)
            axis_x = tracking_x + _clamp(shared_mid - tracking_x, -max_step, max_step)
            return _Observation(
                axis_x=axis_x,
                raw_axis_x=shared_mid,
                run_width=(wl + wr) / 2.0,
                ambiguity_quality=1.0,
                width_quality=1.0,
                symmetric_branch=True,
                trusted_axis=True,
            )

    ranked = sorted(
        candidates,
        key=lambda r: (
            _distance_to_interval(tracking_x, r[0], r[1]),
            -_run_width(r),
            abs(_run_mid(r) - tracking_x),
        ),
    )
    best = ranked[0]
    ambiguity_quality = 1.0
    if len(ranked) > 1:
        a, b = ranked[0], ranked[1]
        score_a = _candidate_scalar_score(a, tracking_x, trusted_width)
        score_b = _candidate_scalar_score(b, tracking_x, trusted_width)
        score_gap = abs(score_b - score_a)
        if score_gap <= 0.08:
            shared_mid = (_run_mid(a) + _run_mid(b)) / 2.0
            max_step = max(config.min_lateral_jump_px, trusted_width * config.max_axis_step_ratio)
            axis_x = tracking_x + _clamp(shared_mid - tracking_x, -max_step, max_step)
            return _Observation(
                axis_x=axis_x,
                raw_axis_x=shared_mid,
                run_width=(_run_width(a) + _run_width(b)) / 2.0,
                ambiguity_quality=0.72,
                width_quality=1.0,
                symmetric_branch=False,
                trusted_axis=True,
            )
        ambiguity_quality = _clamp(0.55 + min(0.45, score_gap), 0.55, 1.0)

    run_mid = _run_mid(best)
    run_width = float(_run_width(best))
    growth = run_width / max(trusted_width, 1e-6)
    max_step = max(config.min_lateral_jump_px, trusted_width * config.max_axis_step_ratio)

    if growth > config.max_width_growth_ratio:
        # v3: do NOT advance the tracker toward an abnormally-wide connected run.
        # The raw midpoint is retained only for diagnostics/continuity scoring.
        # This turns an ambiguous connected-accessory segment into "hold last
        # trusted body axis" instead of many individually-clipped drift steps.
        width_quality = _clamp(config.max_width_growth_ratio / growth, 0.10, 0.65)
        axis_x = tracking_x
        trusted_axis = False
    else:
        width_quality = 1.0
        axis_x = tracking_x + _clamp(run_mid - tracking_x, -max_step, max_step)
        trusted_axis = True

    if abs(axis_x - tracking_x) > gate + 1e-6:
        return None

    return _Observation(
        axis_x=axis_x,
        raw_axis_x=run_mid,
        run_width=run_width,
        ambiguity_quality=ambiguity_quality,
        width_quality=width_quality,
        symmetric_branch=False,
        trusted_axis=trusted_axis,
    )


# ---------------------------------------------------------------------------
# Small deterministic helpers
# ---------------------------------------------------------------------------


def _noop_result(base: FrameTransform, face_before: tuple[float, float], *, reason: str) -> CenteringResult:
    return CenteringResult(
        transform=base,
        analysis=None,
        face_before=face_before,
        face_after=face_before,
        body_before=None,
        body_after=None,
        raw_shift=(0.0, 0.0),
        applied_shift=(0.0, 0.0),
        clamped=False,
        reason=reason,
    )


def _validate_inputs(
    portrait: RasterImage,
    face_point: Sequence[float],
    base: FrameTransform,
    config: CenteringConfig,
) -> None:
    if not all(
        callable(getattr(portrait, name, None))
        for name in ("convert", "getchannel")
    ) or not all(hasattr(portrait, name) for name in ("width", "height")):
        raise TypeError("portrait must provide RGBA raster operations")
    if len(face_point) != 2 or not all(_finite_number(v) for v in face_point):
        raise ValueError("face_point must contain two finite numbers")
    fx, fy = float(face_point[0]), float(face_point[1])
    if not (0.0 <= fx <= portrait.width and 0.0 <= fy <= portrait.height):
        raise ValueError("face_point must be inside portrait source bounds")
    if not all(_finite_number(v) for v in (base.scale, base.left, base.top)):
        raise ValueError("base transform must contain finite numbers")
    if base.scale <= 0:
        raise ValueError("base scale must be positive")
    if not 0 <= config.alpha_threshold <= 255:
        raise ValueError("alpha_threshold must be in [0, 255]")
    if not 0.0 <= config.trim_fraction < 0.5:
        raise ValueError("trim_fraction must be in [0, 0.5)")
    if not 0.0 <= config.body_axis_weight <= 1.0:
        raise ValueError("body_axis_weight must be in [0, 1]")
    if config.bootstrap_band_ratio <= 0 or config.bootstrap_min_rows < 1:
        raise ValueError("bootstrap scale settings must be positive")
    if config.bootstrap_seed_rows < config.bootstrap_min_rows:
        raise ValueError("bootstrap_seed_rows must be >= bootstrap_min_rows")
    if config.bootstrap_core_expansion < 1.0:
        raise ValueError("bootstrap_core_expansion must be >= 1")
    if not 0.0 < config.bootstrap_min_half_balance <= 1.0:
        raise ValueError("bootstrap_min_half_balance must be in (0, 1]")
    if config.bootstrap_min_clean_rows < 1:
        raise ValueError("bootstrap_min_clean_rows must be >= 1")
    if not 0.0 < config.bootstrap_min_clean_fraction <= 1.0:
        raise ValueError("bootstrap_min_clean_fraction must be in (0, 1]")
    if config.bootstrap_max_cluster_ratio <= 1.0 or config.bootstrap_max_bad_rows < 0:
        raise ValueError("bootstrap ambiguity settings are invalid")
    if config.max_tracking_misses < 0:
        raise ValueError("max_tracking_misses must be >= 0")
    if config.max_lateral_jump_ratio <= 0 or config.min_lateral_jump_px < 0:
        raise ValueError("tracking jump limits must be positive")
    if config.max_vertical_gap_ratio <= 0 or config.min_vertical_gap_px < 0:
        raise ValueError("vertical gap limits must be positive")
    if config.max_width_growth_ratio <= 1.0:
        raise ValueError("max_width_growth_ratio must be > 1")
    if config.max_untrusted_span_ratio <= 0:
        raise ValueError("max_untrusted_span_ratio must be positive")
    if not 0.0 <= config.trusted_width_update <= 1.0:
        raise ValueError("trusted_width_update must be in [0, 1]")
    if not 0.0 <= config.min_confidence_for_shift <= 1.0:
        raise ValueError("min_confidence_for_shift must be in [0, 1]")


def _finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value)


def _hist_quantile_index(hist: Sequence[int], quantile: float) -> int | None:
    total = sum(hist)
    if total <= 0:
        return None
    target = max(1.0, _clamp(quantile, 0.0, 1.0) * total)
    cumulative = 0
    for index, weight in enumerate(hist):
        cumulative += weight
        if cumulative >= target:
            return index
    return len(hist) - 1


def _opaque_runs_for_row(
    pixels,
    y: int,
    width: int,
    *,
    threshold: int,
    max_gap: int,
    min_width: int,
) -> list[tuple[int, int]]:
    """Return opaque x-runs, merging only tiny transparent horizontal gaps."""

    runs: list[tuple[int, int]] = []
    start: int | None = None
    last_opaque: int | None = None
    gap = 0

    for x in range(width):
        opaque = pixels[x, y] >= threshold
        if opaque:
            if start is None:
                start = x
            last_opaque = x
            gap = 0
            continue
        if start is None:
            continue
        gap += 1
        if gap > max_gap:
            assert last_opaque is not None
            if last_opaque - start + 1 >= min_width:
                runs.append((start, last_opaque))
            start = None
            last_opaque = None
            gap = 0

    if start is not None and last_opaque is not None:
        if last_opaque - start + 1 >= min_width:
            runs.append((start, last_opaque))
    return runs


def _distance_to_interval(value: float, left: float, right: float) -> float:
    if left <= value <= right:
        return 0.0
    return min(abs(value - left), abs(value - right))


def _run_mid(run: tuple[int, int]) -> float:
    return (run[0] + run[1]) / 2.0


def _run_width(run: tuple[int, int]) -> int:
    return run[1] - run[0] + 1


def _candidate_scalar_score(run: tuple[int, int], tracking_x: float, trusted_width: float) -> float:
    distance = _distance_to_interval(tracking_x, run[0], run[1]) / max(trusted_width, 1.0)
    center_distance = abs(_run_mid(run) - tracking_x) / max(trusted_width, 1.0)
    width_bonus = min(_run_width(run) / max(trusted_width, 1.0), 2.0) * 0.05
    return distance + center_distance * 0.20 - width_bonus


def _weighted_median(values: Sequence[float], weights: Sequence[float]) -> float:
    if len(values) != len(weights) or not values:
        raise ValueError("values and weights must be non-empty and equal length")
    pairs = sorted(zip(values, weights), key=lambda item: item[0])
    total = sum(max(0.0, weight) for _, weight in pairs)
    if total <= 0:
        return pairs[len(pairs) // 2][0]
    threshold = total / 2.0
    cumulative = 0.0
    for value, weight in pairs:
        cumulative += max(0.0, weight)
        if cumulative >= threshold:
            return value
    return pairs[-1][0]


def _safe_delta_bounds(
    current: float,
    safe_min: float,
    safe_max: float,
    max_shift: float,
) -> tuple[float, float]:
    """Return deltas that never move a face farther outside its safe interval.

    If the face starts outside, only movement toward the interval is legal.
    """

    max_shift = abs(max_shift)
    if current < safe_min:
        return 0.0, min(max_shift, max(0.0, safe_max - current))
    if current > safe_max:
        return max(-max_shift, safe_min - current), 0.0
    return (
        max(-max_shift, safe_min - current),
        min(max_shift, safe_max - current),
    )


def _median(values: Sequence[float]) -> float:
    ordered = sorted(float(v) for v in values)
    if not ordered:
        raise ValueError("median requires at least one value")
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _mean(values: Sequence[float], *, default: float) -> float:
    if not values:
        return default
    return sum(values) / len(values)


def _clamp(value: float, lower: float, upper: float) -> float:
    if lower > upper:
        lower, upper = upper, lower
    return min(max(value, lower), upper)
