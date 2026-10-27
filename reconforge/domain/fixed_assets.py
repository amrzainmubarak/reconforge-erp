"""Exact, cumulative straight-line asset accounting; no independent ledger."""

from dataclasses import asdict, dataclass
from datetime import date
from typing import TypedDict

from reconforge.domain.finance_posting import FinancePostingError, text

MAX_MINOR = 9_000_000_000_000_000_000


class AccountingLine(TypedDict):
    account_code: str
    debit_minor: int
    credit_minor: int


def exact_minor(value: object, field: str, *, zero: bool = False) -> int:
    if type(value) is not int or not (0 if zero else 1) <= value <= MAX_MINOR:
        raise FinancePostingError("asset_request_invalid", f"{field} requires bounded exact integer minor units.")
    return value


def cumulative_depreciation(cost: int, salvage: int, life: int, months: int) -> int:
    """Round the cumulative entitlement once, avoiding monthly rounding drift."""
    exact_minor(cost, "cost")
    exact_minor(salvage, "salvage", zero=True)
    if salvage >= cost or type(life) is not int or not 1 <= life <= 1200:
        raise FinancePostingError("asset_request_invalid", "Salvage must be below cost and life between 1 and 1200 months.")
    if type(months) is not int or not 0 <= months <= life:
        raise FinancePostingError("asset_request_invalid", "Depreciation months exceed the retained useful life.")
    return (2 * (cost - salvage) * months + life) // (2 * life)


def eligible_months(in_service_date: str, through_month: str, posting_date: str, life: int) -> int:
    try:
        start, posted = date.fromisoformat(in_service_date), date.fromisoformat(posting_date)
        through = date.fromisoformat(through_month + "-01")
        following = date(through.year + (through.month == 12), through.month % 12 + 1, 1)
    except (TypeError, ValueError) as exc:
        raise FinancePostingError("asset_date_invalid", "Use ISO dates and a YYYY-MM depreciation month.") from exc
    if posted < following:
        raise FinancePostingError("asset_date_invalid", "Depreciation posts after the completed service month.")
    months = (through.year - start.year) * 12 + through.month - start.month + 1
    if months <= 0:
        raise FinancePostingError("asset_date_invalid", "Depreciation cannot precede the service month.")
    return min(months, life)


@dataclass(frozen=True)
class AssetAcquisition:
    workspace_id: str
    organization_id: str
    legal_entity_id: str
    organization_code: str
    entity_code: str
    asset_number: str
    name: str
    journal_code: str
    period_id: str
    posting_date: str
    in_service_date: str
    cost_minor: int
    salvage_minor: int
    useful_life_months: int
    asset_account_code: str
    accumulated_account_code: str
    expense_account_code: str
    cash_account_code: str
    gain_account_code: str
    loss_account_code: str
    reason: str

    def payload(self) -> dict[str, object]:
        value = asdict(self)
        for key, item in value.items():
            if key not in {"cost_minor", "salvage_minor", "useful_life_months"}:
                value[key] = text(item, key, maximum=500 if key == "reason" else 160)
        cumulative_depreciation(self.cost_minor, self.salvage_minor, self.useful_life_months, 0)
        try:
            if date.fromisoformat(self.in_service_date) < date.fromisoformat(self.posting_date):
                raise ValueError("service precedes acquisition")
        except ValueError as exc:
            raise FinancePostingError("asset_date_invalid", "Service date cannot precede acquisition.") from exc
        accounts = [value[key] for key in value if key.endswith("_account_code")]
        if len(accounts) != len(set(accounts)):
            raise FinancePostingError("asset_account_invalid", "Six distinct accounts are required for auditable asset accounting.")
        return value


def accounting_lines(asset: dict[str, object], kind: str, *, accumulated: int = 0,
                     depreciation: int = 0, proceeds: int = 0, impairment: int = 0) -> list[AccountingLine]:
    cost = exact_minor(asset["cost_minor"], "cost")
    exact_minor(accumulated, "accumulated", zero=True)
    if accumulated > cost:
        raise FinancePostingError("asset_state_invalid", "Accumulated depreciation exceeds historical cost.")
    lines: list[AccountingLine] = []

    def add(account: str, debit: int = 0, credit: int = 0) -> None:
        if debit or credit:
            lines.append({"account_code": text(asset[account + "_account_code"], "account_code"), "debit_minor": debit, "credit_minor": credit})

    if kind == "acquire":
        add("asset", debit=cost)
        add("cash", credit=cost)
    elif kind == "depreciate":
        exact_minor(depreciation, "depreciation")
        if accumulated + depreciation > cost - exact_minor(asset["salvage_minor"], "salvage", zero=True):
            raise FinancePostingError("asset_state_invalid", "Depreciation exceeds the retained depreciable basis.")
        add("expense", debit=depreciation)
        add("accumulated", credit=depreciation)
    elif kind == "impair":
        loss = impairment or depreciation
        exact_minor(loss, "impairment")
        if accumulated + loss > cost - exact_minor(asset["salvage_minor"], "salvage", zero=True):
            raise FinancePostingError("asset_state_invalid", "Impairment exceeds the remaining depreciable carrying basis.")
        add("loss", debit=loss)
        add("accumulated", credit=loss)
    elif kind == "dispose":
        exact_minor(proceeds, "proceeds", zero=True)
        exact_minor(impairment, "impairment", zero=True)
        carrying = cost - accumulated - impairment
        add("cash", debit=proceeds)
        add("accumulated", debit=accumulated + impairment)
        add("loss", debit=max(carrying - proceeds, 0))
        add("asset", credit=cost)
        add("gain", credit=max(proceeds - carrying, 0))
    else:
        raise FinancePostingError("asset_request_invalid", "Unsupported asset accounting operation.")
    if sum(row["debit_minor"] for row in lines) > MAX_MINOR:
        raise FinancePostingError("asset_request_invalid", "Disposal turnover exceeds supported native GL bounds.")
    return lines


@dataclass(frozen=True)
class AssetRegister:
    """Configuration and GL accounts for a single accounting/tax/regulatory register."""

    register_code: str
    cost_minor: int
    salvage_minor: int
    useful_life_months: int
    asset_account_code: str
    accumulated_depreciation_account_code: str
    accumulated_impairment_account_code: str
    depreciation_expense_account_code: str
    impairment_loss_account_code: str
    gain_account_code: str
    loss_account_code: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "register_code", text(self.register_code, "register_code", maximum=64))
        exact_minor(self.cost_minor, "cost_minor")
        exact_minor(self.salvage_minor, "salvage_minor", zero=True)
        if self.salvage_minor >= self.cost_minor:
            raise FinancePostingError("asset_request_invalid", "Salvage must be below cost.")
        if type(self.useful_life_months) is not int or not 1 <= self.useful_life_months <= 1200:
            raise FinancePostingError("asset_request_invalid", "Useful life must be between 1 and 1200 months.")
        for key in (
            "asset_account_code",
            "accumulated_depreciation_account_code",
            "accumulated_impairment_account_code",
            "depreciation_expense_account_code",
            "impairment_loss_account_code",
            "gain_account_code",
            "loss_account_code",
        ):
            object.__setattr__(self, key, text(getattr(self, key), key, maximum=64))


@dataclass(frozen=True)
class AssetRegisterState:
    """Historical state and accumulated reserves for an asset register."""

    register_code: str
    accumulated_depreciation_minor: int = 0
    accumulated_impairment_minor: int = 0
    months_depreciated: int = 0
    carrying_value_minor: int = 0

    @classmethod
    def create(
        cls,
        register: AssetRegister,
        *,
        accumulated_depreciation_minor: int = 0,
        accumulated_impairment_minor: int = 0,
        months_depreciated: int = 0,
    ) -> "AssetRegisterState":
        exact_minor(accumulated_depreciation_minor, "accumulated_depreciation_minor", zero=True)
        exact_minor(accumulated_impairment_minor, "accumulated_impairment_minor", zero=True)
        if type(months_depreciated) is not int or not 0 <= months_depreciated <= register.useful_life_months:
            raise FinancePostingError("asset_request_invalid", "Depreciation months exceed the retained useful life.")
        if accumulated_depreciation_minor + accumulated_impairment_minor > register.cost_minor:
            raise FinancePostingError("asset_state_invalid", "Total accumulated deductions exceed asset cost.")
        carrying = register.cost_minor - accumulated_depreciation_minor - accumulated_impairment_minor
        return cls(
            register_code=register.register_code,
            accumulated_depreciation_minor=accumulated_depreciation_minor,
            accumulated_impairment_minor=accumulated_impairment_minor,
            months_depreciated=months_depreciated,
            carrying_value_minor=carrying,
        )

    def with_impairment(self, impairment_loss_minor: int) -> "AssetRegisterState":
        exact_minor(impairment_loss_minor, "impairment_loss_minor", zero=True)
        if impairment_loss_minor > self.carrying_value_minor:
            raise FinancePostingError("asset_state_invalid", "Impairment loss exceeds carrying value.")
        new_accum_impair = self.accumulated_impairment_minor + impairment_loss_minor
        new_carrying = self.carrying_value_minor - impairment_loss_minor
        return AssetRegisterState(
            register_code=self.register_code,
            accumulated_depreciation_minor=self.accumulated_depreciation_minor,
            accumulated_impairment_minor=new_accum_impair,
            months_depreciated=self.months_depreciated,
            carrying_value_minor=new_carrying,
        )

    def with_depreciation(self, depreciation_minor: int, months: int = 1) -> "AssetRegisterState":
        exact_minor(depreciation_minor, "depreciation_minor", zero=True)
        if depreciation_minor > self.carrying_value_minor:
            raise FinancePostingError("asset_state_invalid", "Depreciation exceeds carrying value.")
        new_accum_depr = self.accumulated_depreciation_minor + depreciation_minor
        new_carrying = self.carrying_value_minor - depreciation_minor
        return AssetRegisterState(
            register_code=self.register_code,
            accumulated_depreciation_minor=new_accum_depr,
            accumulated_impairment_minor=self.accumulated_impairment_minor,
            months_depreciated=self.months_depreciated + months,
            carrying_value_minor=new_carrying,
        )


@dataclass(frozen=True)
class MultiRegisterAssetAcquisition:
    """Multi-register asset acquisition model supporting statutory, tax, and IFRS registers."""

    workspace_id: str
    organization_id: str
    legal_entity_id: str
    organization_code: str
    entity_code: str
    asset_number: str
    name: str
    journal_code: str
    period_id: str
    posting_date: str
    in_service_date: str
    registers: tuple[AssetRegister, ...]
    cash_account_code: str
    reason: str = "Multi-register asset acquisition"

    def __post_init__(self) -> None:
        if not self.registers:
            raise FinancePostingError("asset_request_invalid", "At least one asset register is required.")
        reg_codes = [r.register_code for r in self.registers]
        if len(set(reg_codes)) != len(reg_codes):
            raise FinancePostingError("asset_request_invalid", "Asset register codes must be distinct.")
        for key in (
            "workspace_id", "organization_id", "legal_entity_id", "organization_code",
            "entity_code", "asset_number", "name", "journal_code", "period_id",
            "posting_date", "in_service_date", "cash_account_code", "reason",
        ):
            object.__setattr__(self, key, text(getattr(self, key), key, maximum=500 if key == "reason" else 160))
        try:
            if date.fromisoformat(self.in_service_date) < date.fromisoformat(self.posting_date):
                raise ValueError("service precedes acquisition")
        except ValueError as exc:
            raise FinancePostingError("asset_date_invalid", "Service date cannot precede acquisition.") from exc

    def acquisition_lines(self, primary_register_code: str | None = None) -> list[AccountingLine]:
        primary = self.registers[0]
        if primary_register_code:
            found = [r for r in self.registers if r.register_code == primary_register_code]
            if not found:
                raise FinancePostingError("asset_request_invalid", f"Primary register '{primary_register_code}' not found.")
            primary = found[0]
        return [
            {"account_code": primary.asset_account_code, "debit_minor": primary.cost_minor, "credit_minor": 0},
            {"account_code": self.cash_account_code, "debit_minor": 0, "credit_minor": primary.cost_minor},
        ]


def impairment_lines(
    register: AssetRegister,
    state: AssetRegisterState,
    recoverable_amount_minor: int,
) -> tuple[int, list[AccountingLine]]:
    """Determine impairment loss and generate balanced GL lines (debit loss, credit accumulated impairment)."""
    exact_minor(recoverable_amount_minor, "recoverable_amount", zero=True)
    carrying = state.carrying_value_minor
    if recoverable_amount_minor >= carrying:
        return 0, []
    loss = carrying - recoverable_amount_minor
    if loss > MAX_MINOR:
        raise FinancePostingError("asset_request_invalid", "Impairment loss exceeds native GL bounds.")
    lines: list[AccountingLine] = [
        {
            "account_code": register.impairment_loss_account_code,
            "debit_minor": loss,
            "credit_minor": 0,
        },
        {
            "account_code": register.accumulated_impairment_account_code,
            "debit_minor": 0,
            "credit_minor": loss,
        },
    ]
    return loss, lines


def cumulative_post_impairment_depreciation(
    remaining_depreciable_basis_minor: int,
    remaining_life_months: int,
    elapsed_months_since_impairment: int,
) -> int:
    """Calculate cumulative post-impairment straight-line depreciation with half-up integer rounding."""
    exact_minor(remaining_depreciable_basis_minor, "remaining_depreciable_basis", zero=True)
    if type(remaining_life_months) is not int or remaining_life_months <= 0:
        return 0
    if type(elapsed_months_since_impairment) is not int or not 0 <= elapsed_months_since_impairment <= remaining_life_months:
        raise FinancePostingError("asset_request_invalid", "Elapsed months must be within remaining useful life.")
    if elapsed_months_since_impairment == 0:
        return 0
    return (2 * remaining_depreciable_basis_minor * elapsed_months_since_impairment + remaining_life_months) // (2 * remaining_life_months)


def recalibrate_post_impairment_depreciation(
    register: AssetRegister,
    state: AssetRegisterState,
    elapsed_months_since_impairment: int,
) -> int:
    """Determine cumulative revised depreciation charge from post-impairment carrying basis."""
    carrying = state.carrying_value_minor
    salvage = register.salvage_minor
    remaining_basis = max(carrying - salvage, 0)
    remaining_life = register.useful_life_months - state.months_depreciated
    return cumulative_post_impairment_depreciation(remaining_basis, remaining_life, elapsed_months_since_impairment)


def multi_register_disposal_lines(
    asset: MultiRegisterAssetAcquisition,
    states: dict[str, AssetRegisterState],
    proceeds_minor: int,
    proceeds_cash_account: str,
    *,
    proceeds_allocation: dict[str, int] | None = None,
) -> dict[str, list[AccountingLine]]:
    """Generate exact balanced disposal GL lines across all registers with zero float."""
    exact_minor(proceeds_minor, "proceeds_minor", zero=True)
    cash_acc = text(proceeds_cash_account, "proceeds_cash_account", maximum=64)
    result: dict[str, list[AccountingLine]] = {}
    for register in asset.registers:
        reg_code = register.register_code
        if reg_code not in states:
            raise FinancePostingError("asset_state_invalid", f"Missing state for register '{reg_code}'.")
        state = states[reg_code]
        cost = register.cost_minor
        accum_depr = state.accumulated_depreciation_minor
        accum_impair = state.accumulated_impairment_minor
        carrying = cost - accum_depr - accum_impair
        if carrying < 0:
            raise FinancePostingError("asset_state_invalid", f"Negative carrying value on register '{reg_code}'.")
        reg_proceeds = proceeds_allocation[reg_code] if (proceeds_allocation and reg_code in proceeds_allocation) else proceeds_minor
        exact_minor(reg_proceeds, f"proceeds for register {reg_code}", zero=True)

        lines: list[AccountingLine] = []
        if reg_proceeds > 0:
            lines.append({"account_code": cash_acc, "debit_minor": reg_proceeds, "credit_minor": 0})
        if accum_depr > 0:
            lines.append({"account_code": register.accumulated_depreciation_account_code, "debit_minor": accum_depr, "credit_minor": 0})
        if accum_impair > 0:
            lines.append({"account_code": register.accumulated_impairment_account_code, "debit_minor": accum_impair, "credit_minor": 0})
        lines.append({"account_code": register.asset_account_code, "debit_minor": 0, "credit_minor": cost})

        if reg_proceeds > carrying:
            gain = reg_proceeds - carrying
            lines.append({"account_code": register.gain_account_code, "debit_minor": 0, "credit_minor": gain})
        elif reg_proceeds < carrying:
            loss = carrying - reg_proceeds
            lines.append({"account_code": register.loss_account_code, "debit_minor": loss, "credit_minor": 0})

        debit_total = sum(line["debit_minor"] for line in lines)
        credit_total = sum(line["credit_minor"] for line in lines)
        if debit_total != credit_total:
            raise FinancePostingError(
                "asset_balance_invalid",
                f"Disposal lines for register {reg_code} do not balance: Debit {debit_total} != Credit {credit_total}",
            )
        result[reg_code] = lines
    return result

