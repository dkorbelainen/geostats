import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import quote as _url_quote

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from sqlalchemy import func
from sqlalchemy.orm import Session

from geostats.api.deps import get_db, get_geo_client
from geostats.client import GeoClient
from geostats.models import Account, AccountAnomaly, PlayerMatch, RatingSnapshot
from geostats.stats.aggregates import summarize_profile
from geostats.stats.anomalies import CONFIDENCE_DISPLAY_THRESHOLD
from geostats.stats.forecast import ForecastResult, forecast_rating
from geostats.stats.series import get_series

router = APIRouter()

_templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=_templates_dir)

_ID_RE = re.compile(r"^[A-Za-z0-9]{20,24}$")
_URL_RE = re.compile(r"geoguessr\.com/user/([A-Za-z0-9]{20,24})")


def parse_user_id(value: str) -> str:
    value = value.strip()
    m = _URL_RE.search(value)
    if m:
        return m.group(1)
    if _ID_RE.match(value):
        return value
    raise LookupError(f"invalid user id or url: {value!r}")


def _slug_base(nick: str) -> str:
    s = re.sub(r"[^a-zа-яё0-9_]", "", nick.lower().replace(" ", "_"))
    return s.strip("_")


def _assign_slug(db: Session, account: Account) -> None:
    base = _slug_base(account.nick)
    if not base:
        return
    slug = base
    n = 2
    while (
        db.query(Account).filter(Account.slug == slug, Account.id != account.id).first()
        is not None
    ):
        slug = f"{base}_{n}"
        n += 1
    account.slug = slug


def _fmt_rating(v: object) -> str:
    if not isinstance(v, int):
        return "—"
    return f"{v:,}".replace(",", " ")


def _fmt_delta(v: object) -> str:
    if not isinstance(v, int):
        return "—"
    if v > 0:
        return f"+{v}"
    if v < 0:
        return f"−{abs(v)}"
    return "—"


def _fmt_rank(v: object) -> str:
    if not isinstance(v, int):
        return "—"
    return f"#{v}"


_CC_LEN = 2
_SECS_MINUTE = 60
_SECS_HOUR = 3600
_SECS_DAY = 86400


_ZZ_GLOBE = "🌎"


def _country_flag(code: object) -> str:
    if not isinstance(code, str) or len(code) != _CC_LEN:
        return ""
    if code.upper() == "ZZ":
        return _ZZ_GLOBE
    return "".join(chr(0x1F1E6 - 65 + ord(c.upper())) for c in code)


def _flag_img(code: object) -> Markup:
    if not isinstance(code, str) or len(code) != _CC_LEN:
        return Markup("")
    if code.upper() == "ZZ":
        return Markup(_ZZ_GLOBE)
    cc = code.lower()
    return Markup(f'<img class="flag-img" src="https://flagcdn.com/{cc}.svg" alt="{code.upper()}">')


def _time_ago(dt: object) -> str:
    if not isinstance(dt, datetime):
        return "unknown"
    now = datetime.now(tz=UTC)
    diff = int((now - dt).total_seconds())
    if diff < _SECS_MINUTE:
        return "just now"
    if diff < _SECS_HOUR:
        return f"{diff // _SECS_MINUTE}m ago"
    if diff < _SECS_DAY:
        return f"{diff // _SECS_HOUR}h ago"
    return f"{diff // _SECS_DAY}d ago"


_ANOMALY_LABELS: dict[str, str] = {
    "peak_rating": "Peak rating",
    "mean_rating": "Average rating",
    "rating_volatility": "Rating volatility",
    "rating_delta": "Rating growth",
    "peak_win_streak": "Peak win streak",
    "mean_guessed_first_rate": "Guess speed",
    "winrate": "Win rate",
    "mean_avg_guess_distance_km": "Average distance",
    "log_games": "Games volume",
}


def _anomaly_view(row: AccountAnomaly | None) -> dict[str, object] | None:
    if row is None or row.confidence_pct < CONFIDENCE_DISPLAY_THRESHOLD:
        return None
    drivers: list[dict[str, str]] = []
    pairs = [(row.driver_1_feature, row.driver_1_z),
             (row.driver_2_feature, row.driver_2_z)]
    for feature, z in pairs:
        if feature is None or z is None:
            continue
        drivers.append({
            "feature": feature,
            "label": _ANOMALY_LABELS.get(feature, feature),
            "direction": "up" if z > 0 else "down",
        })
    return {"confidence_pct": row.confidence_pct, "drivers": drivers}


async def resolve_profile(
    value: str, db: Session, client: GeoClient
) -> tuple[str, str | None]:
    value = value.strip()
    m = _URL_RE.search(value)
    if m:
        return m.group(1), None
    if _ID_RE.match(value):
        return value, None
    account = (
        db.query(Account).filter(func.lower(Account.nick) == value.lower()).first()
    )
    if account is not None:
        return account.id, None
    try:
        results = await client.search_user(value)
    except Exception:
        raise LookupError("Search unavailable, try a profile URL") from None
    if not results:
        raise LookupError(f'No player found for "{value}"')
    first = results[0]
    return first.user_id, first.nick


_LB_MODE_FIELDS = {
    "overall": (RatingSnapshot.rating,        RatingSnapshot.position_overall),
    "moving":  (RatingSnapshot.rating_moving, RatingSnapshot.position_moving),
    "nomove":  (RatingSnapshot.rating_nomove, RatingSnapshot.position_nomove),
    "nmpz":    (RatingSnapshot.rating_nmpz,   RatingSnapshot.position_nmpz),
}

templates.env.filters["url_path"] = lambda v: _url_quote(str(v), safe="")
templates.env.filters["fmt_rating"] = _fmt_rating
templates.env.filters["fmt_delta"] = _fmt_delta
templates.env.filters["fmt_rank"] = _fmt_rank
templates.env.filters["country_flag"] = _country_flag
templates.env.filters["flag_img"] = _flag_img
templates.env.filters["time_ago"] = _time_ago
templates.env.globals["getattr"] = getattr


_LB_VALID_LIMITS = frozenset({25, 100, 250, 500})


@router.get("/leaderboard")
async def leaderboard(
    request: Request,
    mode: Literal["overall", "moving", "nomove", "nmpz"] = Query(default="overall"),
    limit: int = Query(default=100, ge=1),
    db: Session = Depends(get_db),  # noqa: B008
) -> Response:
    if limit not in _LB_VALID_LIMITS:
        limit = 100
    rating_col, pos_col = _LB_MODE_FIELDS[mode]
    latest_snap_sq = (
        db.query(func.max(RatingSnapshot.captured_at))
        .filter(RatingSnapshot.account_id == Account.id)
        .correlate(Account)
        .scalar_subquery()
    )
    rows = (
        db.query(Account, RatingSnapshot)
        .join(
            RatingSnapshot,
            (RatingSnapshot.account_id == Account.id)
            & (RatingSnapshot.captured_at == latest_snap_sq),
        )
        .filter(
            Account.tracked == True,  # noqa: E712
            Account.last_polled_at.isnot(None),
            rating_col.isnot(None),
        )
        .order_by(rating_col.desc())
        .limit(limit)
        .all()
    )
    return templates.TemplateResponse(
        request,
        "leaderboard.html",
        {"rows": rows, "mode": mode, "limit": limit},
    )


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/")
async def landing(
    request: Request, db: Session = Depends(get_db)  # noqa: B008
) -> Response:
    latest_snap_sq = (
        db.query(func.max(RatingSnapshot.captured_at))
        .filter(RatingSnapshot.account_id == Account.id)
        .correlate(Account)
        .scalar_subquery()
    )
    top_profiles = (
        db.query(Account, RatingSnapshot)
        .join(
            RatingSnapshot,
            (RatingSnapshot.account_id == Account.id)
            & (RatingSnapshot.captured_at == latest_snap_sq),
        )
        .filter(Account.last_polled_at.isnot(None))
        .order_by(Account.lookup_count.desc())
        .limit(6)
        .all()
    )
    return templates.TemplateResponse(
        request, "landing.html", {"top_profiles": top_profiles}
    )


@router.post("/lookup")
async def lookup(
    request: Request,
    profile: str = Form(...),
    db: Session = Depends(get_db),  # noqa: B008
    client: GeoClient = Depends(get_geo_client),  # noqa: B008
) -> Response:
    try:
        user_id, nick = await resolve_profile(profile, db, client)
    except LookupError as exc:
        return templates.TemplateResponse(
            request,
            "landing.html",
            {"error": str(exc), "top_profiles": []},
            status_code=400,
        )

    account = db.get(Account, user_id)
    if account is None:
        now = datetime.now(tz=UTC)
        account = Account(id=user_id, nick=nick or user_id, tracked=True, created_at=now)
        db.add(account)
    elif nick is not None and account.nick != nick:
        account.nick = nick
        account.slug = None
    if account.slug is None:
        _assign_slug(db, account)
    account.lookup_count += 1
    db.commit()

    return RedirectResponse(url=f"/profile/{_url_quote(str(account.slug or user_id), safe='')}", status_code=303)


@router.get("/profile/{profile_ref}")
async def profile_page(
    profile_ref: str,
    request: Request,
    forecast: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),  # noqa: B008
) -> Response:
    if len(profile_ref) > 100:
        raise HTTPException(status_code=404)

    account = db.get(Account, profile_ref)
    if account is None:
        account = (
            db.query(Account).filter(Account.slug == profile_ref.lower()).first()
        )
    if account is None:
        raise HTTPException(status_code=404)

    account.lookup_count += 1
    db.commit()

    if account.last_polled_at is None:
        return templates.TemplateResponse(
            request,
            "profile.html",
            {"account": account, "collecting": True},
        )

    snaps: list[RatingSnapshot] = (
        db.query(RatingSnapshot)
        .filter(RatingSnapshot.account_id == account.id)
        .order_by(RatingSnapshot.captured_at.asc())
        .all()
    )

    total_tracked: int = (
        db.query(func.count(Account.id))
        .filter(Account.tracked == True, Account.last_polled_at.isnot(None))  # noqa: E712
        .scalar()
        or 0
    )

    summary = summarize_profile(account, snaps, total_tracked=total_tracked)

    def _latest_rating(account_id: str | None) -> int | None:
        if not account_id:
            return None
        return (
            db.query(RatingSnapshot.rating)
            .filter(RatingSnapshot.account_id == account_id, RatingSnapshot.rating.isnot(None))
            .order_by(RatingSnapshot.captured_at.desc())
            .limit(1)
            .scalar()
        )

    pm = db.get(PlayerMatch, account.id)
    anomaly_row = db.get(AccountAnomaly, account.id)
    anomaly = _anomaly_view(anomaly_row)
    doppel: dict[str, Account | int | None] = {
        "global": db.get(Account, pm.global_match_id) if pm and pm.global_match_id else None,
        "global_sim": pm.global_similarity if pm else None,
        "global_rating": _latest_rating(pm.global_match_id if pm else None),
        "country": db.get(Account, pm.country_match_id) if pm and pm.country_match_id else None,
        "country_sim": pm.country_similarity if pm else None,
        "country_rating": _latest_rating(pm.country_match_id if pm else None),
    }

    fc_7d = forecast_rating(snaps, "overall", 7)
    fc_30d = forecast_rating(snaps, "overall", 30)
    fc_custom: ForecastResult | None = (
        forecast_rating(snaps, "overall", forecast) if forecast not in (7, 30) else None
    )

    return templates.TemplateResponse(
        request,
        "profile.html",
        {
            "summary": summary,
            "collecting": False,
            "fc_7d": fc_7d,
            "fc_30d": fc_30d,
            "fc_custom": fc_custom,
            "forecast_horizon": forecast,
            "doppel": doppel,
            "anomaly": anomaly,
        },
    )


@router.get("/api/search")
async def search_accounts(
    q: str = Query(default=""),
    db: Session = Depends(get_db),  # noqa: B008
) -> list[dict[str, object]]:
    if len(q) < 2:
        return []
    latest_snap_sq = (
        db.query(func.max(RatingSnapshot.captured_at))
        .filter(RatingSnapshot.account_id == Account.id)
        .correlate(Account)
        .scalar_subquery()
    )
    rows = (
        db.query(Account, RatingSnapshot)
        .outerjoin(
            RatingSnapshot,
            (RatingSnapshot.account_id == Account.id)
            & (RatingSnapshot.captured_at == latest_snap_sq),
        )
        .filter(
            Account.nick.ilike(f"%{q}%"),
            Account.last_polled_at.isnot(None),
        )
        .order_by(Account.lookup_count.desc())
        .limit(8)
        .all()
    )
    return [
        {
            "id": row.Account.id,
            "nick": row.Account.nick,
            "slug": row.Account.slug,
            "country_code": row.Account.country_code,
            "rating": row.RatingSnapshot.rating if row.RatingSnapshot else None,
        }
        for row in rows
    ]


@router.get("/api/profile/{user_id}/series")
async def series_api(
    user_id: str,
    db: Session = Depends(get_db),  # noqa: B008
    mode: Literal["overall", "moving", "nomove", "nmpz"] = Query(default="overall"),
    range_: Literal["7d", "30d", "90d", "all"] = Query(default="30d", alias="range"),
) -> dict[str, object]:
    account = db.get(Account, user_id)
    if account is None:
        raise HTTPException(status_code=404, detail="not found")

    snaps: list[RatingSnapshot] = (
        db.query(RatingSnapshot)
        .filter(RatingSnapshot.account_id == user_id)
        .order_by(RatingSnapshot.captured_at.asc())
        .all()
    )
    points = get_series(snaps, mode, range_)
    return {"mode": mode, "range": range_, "points": points}


@router.get("/api/profile/{user_id}/forecast")
async def forecast_api(
    user_id: str,
    db: Session = Depends(get_db),  # noqa: B008
    mode: Literal["overall", "moving", "nomove", "nmpz"] = Query(default="overall"),
    horizon: int = Query(default=30, ge=1, le=365),
) -> dict[str, object]:
    account = db.get(Account, user_id)
    if account is None:
        raise HTTPException(status_code=404, detail="not found")

    snaps: list[RatingSnapshot] = (
        db.query(RatingSnapshot)
        .filter(RatingSnapshot.account_id == user_id)
        .order_by(RatingSnapshot.captured_at.asc())
        .all()
    )
    result = forecast_rating(snaps, mode, horizon)
    return {
        "horizon": result.horizon_days,
        "mode": mode,
        "predicted_delta": result.predicted_delta,
        "predicted_rating": result.predicted_rating,
        "confidence": result.confidence,
        "n_points": result.n_points,
    }
