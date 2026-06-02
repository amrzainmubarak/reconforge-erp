"""Directory anonymization engine."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from reconforge.anonymizer.mapping import AnonymizationMap
from reconforge.anonymizer.maskers import mask_frame
from reconforge.io.readers import normalize_columns, read_table


def anonymize_directory(
    input_dir: Path | str,
    output_dir: Path | str,
    *,
    mask_amounts: bool = False,
    amount_noise_percent: float = 15.0,
    seed: int = 42,
    preserve_dates: bool = False,
    date_shift_days: int = 0,
    profile: str = "consulting-safe",
) -> list[Path]:
    """Anonymize CSV exports while preserving referential integrity."""

    source = Path(input_dir)
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    if profile == "public-demo":
        mask_amounts = True
        preserve_dates = False
        date_shift_days = date_shift_days or 30
        amount_noise_percent = amount_noise_percent or 10.0
    elif profile == "consulting-safe":
        preserve_dates = preserve_dates
    elif profile not in {"consulting-safe", "public-demo"}:
        raise ValueError("profile must be one of: consulting-safe, public-demo")
    mapping = AnonymizationMap(seed=seed)
    outputs: list[Path] = []
    for path in sorted(source.glob("*.csv")):
        frame = normalize_columns(read_table(path))
        masked = mask_frame(
            frame,
            mapping,
            mask_amounts=mask_amounts,
            amount_noise_percent=amount_noise_percent,
            preserve_dates=preserve_dates,
            date_shift_days=date_shift_days,
        )
        output_path = target / path.name
        masked.to_csv(output_path, index=False)
        outputs.append(output_path)
    mapping_frame = pd.DataFrame(
        [{"group": group, "original": original, "masked": masked} for (group, original), masked in mapping.values.items()],
    )
    mapping_frame.to_csv(target / "anonymization_map.csv", index=False)
    outputs.append(target / "anonymization_map.csv")
    return outputs
