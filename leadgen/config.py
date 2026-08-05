"""Loading and validating the research config (markets, categories, ICP)."""

from dataclasses import dataclass, field

try:
    import yaml
except ImportError:  # pragma: no cover - dependency is declared in requirements
    yaml = None


DEFAULT_WEIGHTS = {
    "uses_whatsapp": 35,
    "independent": 20,
    "reachable_email": 15,
    "right_size": 15,
    "good_rating": 10,
    "has_phone": 10,
    "contact_form_only": 10,
    "has_website": 5,
    "has_booking_engine": -10,
    "no_web_presence": -15,
}

# Tier boundaries, applied to the 0-100 normalized fit score.
DEFAULT_TIERS = {"A": 70, "B": 45, "C": 0}


@dataclass
class ICP:
    """Ideal customer profile — what makes a business worth contacting."""

    name: str = "Independent local rental operator"
    weights: dict = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    review_count_range: tuple = (5, 400)
    min_rating: float = 3.5
    exclude_chains: bool = True
    exclude_permanently_closed: bool = True
    tiers: dict = field(default_factory=lambda: dict(DEFAULT_TIERS))

    @property
    def max_positive_score(self):
        """Sum of the positive weights — used to normalize scores to 0-100."""
        total = sum(w for w in self.weights.values() if w > 0)
        return total or 1


@dataclass
class Category:
    """A business category to search for, in the words Google will match."""

    id: str
    query: str

    @property
    def label(self):
        return self.id.replace("_", " ")


@dataclass
class Market:
    """One place to research: a city, plus how to talk to Google about it."""

    city: str
    country: str
    language: str = ""  # ISO 639-1, e.g. "pt" — results come back localized
    region: str = ""  # ccTLD, e.g. "pt" — biases ranking toward that country
    areas: list = field(default_factory=list)
    currency: str = ""
    notes: str = ""

    @property
    def id(self):
        return f"{self.city}, {self.country}"

    def queries(self, category):
        """Search strings for this market.

        Google caps Text Search at 60 results per query, so listing
        neighbourhoods under `areas` is how you get past that ceiling in a
        dense city — each area is a separate query, deduplicated by place_id.
        """
        if not self.areas:
            return [f"{category.query} in {self.city}, {self.country}"]
        return [
            f"{category.query} in {area}, {self.city}, {self.country}"
            for area in self.areas
        ]


@dataclass
class ResearchConfig:
    icp: ICP = field(default_factory=ICP)
    categories: list = field(default_factory=list)
    markets: list = field(default_factory=list)
    max_per_market: int = 40
    crawl_websites: bool = True

    @property
    def planned_queries(self):
        return sum(len(m.queries(c)) for m in self.markets for c in self.categories)


def _as_tuple_range(value, fallback):
    if not value:
        return fallback
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return (float(value[0]), float(value[1]))
    raise ValueError(f"expected a [min, max] pair, got {value!r}")


def load_config(path):
    """Read a YAML research config. Raises ValueError with a readable message."""
    if yaml is None:
        raise ValueError("PyYAML is not installed — run: pip install -r requirements.txt")

    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
    except FileNotFoundError:
        raise ValueError(f"config file not found: {path}")
    except yaml.YAMLError as exc:
        raise ValueError(f"could not parse {path}: {exc}")

    if not isinstance(raw, dict):
        raise ValueError(f"{path} should contain a YAML mapping at the top level")

    icp_raw = raw.get("icp") or {}
    weights = dict(DEFAULT_WEIGHTS)
    weights.update(icp_raw.get("weights") or {})
    icp = ICP(
        name=icp_raw.get("name", ICP.name),
        weights=weights,
        review_count_range=_as_tuple_range(icp_raw.get("review_count_range"), (5, 400)),
        min_rating=float(icp_raw.get("min_rating", 3.5)),
        exclude_chains=bool(icp_raw.get("exclude_chains", True)),
        exclude_permanently_closed=bool(icp_raw.get("exclude_permanently_closed", True)),
        tiers={**DEFAULT_TIERS, **(icp_raw.get("tiers") or {})},
    )

    categories = []
    for entry in raw.get("categories") or []:
        if isinstance(entry, str):
            categories.append(Category(id=entry.replace(" ", "_"), query=entry))
            continue
        if not entry.get("query"):
            raise ValueError(f"category {entry!r} is missing a 'query'")
        categories.append(
            Category(id=entry.get("id") or entry["query"].replace(" ", "_"), query=entry["query"])
        )
    if not categories:
        raise ValueError(f"{path} lists no categories — add at least one under 'categories'")

    markets = []
    for entry in raw.get("markets") or []:
        if not isinstance(entry, dict) or not entry.get("city"):
            raise ValueError(f"market {entry!r} needs at least a 'city'")
        markets.append(
            Market(
                city=entry["city"],
                country=entry.get("country", ""),
                language=entry.get("language", ""),
                region=entry.get("region", ""),
                areas=list(entry.get("areas") or []),
                currency=entry.get("currency", ""),
                notes=entry.get("notes", ""),
            )
        )
    if not markets:
        raise ValueError(f"{path} lists no markets — add at least one under 'markets'")

    return ResearchConfig(
        icp=icp,
        categories=categories,
        markets=markets,
        max_per_market=int(raw.get("max_per_market", 40)),
        crawl_websites=bool(raw.get("crawl_websites", True)),
    )
