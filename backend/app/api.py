"""REST API: catalog browsing, add-book / wishlist, lookup & barcode decode,
plus the opt-in enrichment workflow."""
import io
import json
import os
import tarfile

from flask import Blueprint, Response, current_app, jsonify, request, send_file
from sqlalchemy import func

from .config import Config
from .db import Session
from . import models as m
from . import enrichment
from flask import session

from . import catalog
from . import query as qmod
from .auth import require_auth, is_admin, hash_password
from .lookup import lookup as isbn_lookup

bp = Blueprint("api", __name__, url_prefix="/api")


@bp.before_request
def _guard():
    # Gate every /api/* route: 401 if not logged in, 403 if a readonly account writes.
    return require_auth()


def _author_names(work):
    return [c.author.canonical_name for c in work.contributors]


def _work_json(w):
    return {
        "id": w.id,
        "title": w.title,
        "sort_title": w.sort_title,
        "authors": _author_names(w),
        "original_language": w.original_language,
        "series": w.series.name if w.series else None,
        "series_position": w.series_position,
        "tags": [t.tag.name for t in w.tags],
        "editions": [
            {
                "id": e.id, "isbn13": e.isbn13, "isbn10": e.isbn10, "publisher": e.publisher,
                "year": e.published_year, "published_date": e.published_date.isoformat() if e.published_date else None,
                "format": e.format, "language": e.language,
                "pages": e.pages, "cover_path": e.cover_path,
                "list_price": float(e.list_price) if e.list_price is not None else None,
                "list_price_currency": e.list_price_currency,
                "description": e.description,
                "contributors": [{"name": ec.author.canonical_name, "role": ec.role} for ec in e.contributors],
                "identifiers": [{"scheme": i.scheme, "value": i.value} for i in e.identifiers],
                "copies": [
                    {
                        "id": c.id, "kind": c.kind, "copy_type": c.copy_type,
                        "condition": c.condition, "condition_grade": c.condition_grade,
                        "location": c.location, "signed": c.signed, "notes": c.notes,
                        "file_ref": c.file_ref,
                        "acquired_date": c.acquired_date.isoformat() if c.acquired_date else None,
                        "acquisition_price": float(c.acquisition_price) if c.acquisition_price is not None else None,
                        "acquisition_currency": c.acquisition_currency,
                        "current_value": float(c.current_value) if c.current_value is not None else None,
                        "current_value_currency": c.current_value_currency,
                        "reading": [
                            {"status": r.status, "started": r.started.isoformat() if r.started else None,
                             "finished": r.finished.isoformat() if r.finished else None,
                             "progress_pct": r.progress_pct}
                            for r in c.reading_sessions
                        ],
                    }
                    for c in e.copies
                ],
            }
            for e in w.editions
        ],
    }


@bp.post("/import/preview")
def import_preview():
    """Parse an uploaded CSV and stage rows (no writes)."""
    f = request.files.get("file")
    if not f:
        return jsonify(error="no file uploaded"), 400
    from .csvimport import parse_csv
    return jsonify(parse_csv(f.read()))


@bp.post("/import/commit")
def import_commit():
    """Add selected staged rows to Library or Wishlist (optional collection + lookup)."""
    from .csvimport import commit
    data = request.get_json(silent=True) or {}
    dest = data.get("destination")
    if dest not in ("library", "wishlist"):
        return jsonify(error="destination must be library|wishlist"), 400
    res = commit(Session(), data.get("rows", []), dest,
                 collection_id=data.get("collection_id"), do_lookup=bool(data.get("do_lookup")))
    return jsonify(res)


@bp.get("/dq/values")
def dq_values():
    if not is_admin():
        return jsonify(error="admin only"), 403
    from .dq import field_values
    return jsonify(values=field_values(Session(), request.args.get("field", "")))


@bp.get("/dq/clusters")
def dq_clusters():
    if not is_admin():
        return jsonify(error="admin only"), 403
    from .dq import cluster_values
    try:
        th = float(request.args.get("threshold", 0.84))
    except ValueError:
        th = 0.84
    return jsonify(clusters=cluster_values(Session(), request.args.get("field", ""), threshold=th))


@bp.post("/dq/replace")
def dq_replace():
    from .dq import replace_value
    d = request.get_json(silent=True) or {}
    res = replace_value(Session(), d.get("field"), d.get("from"), d.get("to"))
    return jsonify(res), (200 if res.get("ok") else 400)


@bp.get("/fields")
def list_fields():
    """Model-introspected field catalog for the filter/sort/search menus, enriched with
    friendly labels, one-line help and example values."""
    return jsonify(fields=qmod.fields_for_ui(Session()), ops=qmod.OPS)


@bp.post("/search/reindex")
def search_reindex():
    """Admin: rebuild the full-text search index for all works."""
    if not is_admin():
        return jsonify(error="admin only"), 403
    from .search import reindex
    reindex(Session())
    return jsonify(ok=True, works=Session().query(m.Work).count())


@bp.get("/works")
def list_works():
    s = Session()
    filters = []
    raw = request.args.get("filters")
    if raw:
        try:
            filters = json.loads(raw)
        except ValueError:
            filters = []
    query = qmod.build_works_query(
        s, q=request.args.get("q"), search_field=request.args.get("search_field"),
        filters=filters, sort=request.args.get("sort"),
        direction=request.args.get("dir", "asc"), tag=request.args.get("tag"),
        collection_id=request.args.get("collection_id"),
    )
    limit = min(int(request.args.get("limit", 50)), 500)
    offset = int(request.args.get("offset", 0))
    total = query.count()
    works = query.limit(limit).offset(offset).all()
    return jsonify(total=total, limit=limit, offset=offset,
                   works=[_work_json(w) for w in works])


def _work_json_full(w):
    """Everything in _work_json PLUS the rest of the data model (author birth/death +
    name variants, non-ISBN identifiers are already in base, per-copy loans, legacy id,
    catalogue timestamps) — for the Detail view, which shows the complete record."""
    base = _work_json(w)
    base["created_at"] = w.created_at.isoformat() if w.created_at else None
    base["updated_at"] = w.updated_at.isoformat() if w.updated_at else None
    base["authors_detail"] = [
        {"name": c.author.canonical_name, "role": c.role, "sort_name": c.author.sort_name,
         "birth_year": c.author.birth_year, "death_year": c.author.death_year,
         "name_forms": [nf.name_form for nf in c.author.name_forms]}
        for c in w.contributors
    ]
    for ej, e in zip(base["editions"], w.editions):
        ej["published_year"] = e.published_year
        ej["created_at"] = e.created_at.isoformat() if e.created_at else None
        for cj, c in zip(ej["copies"], e.copies):
            cj["legacy_book_uuid"] = c.legacy_book_uuid
            cj["created_at"] = c.created_at.isoformat() if c.created_at else None
            cj["loans"] = [
                {"borrower": ln.borrower,
                 "lent_date": ln.lent_date.isoformat() if ln.lent_date else None,
                 "due_date": ln.due_date.isoformat() if ln.due_date else None,
                 "returned_date": ln.returned_date.isoformat() if ln.returned_date else None}
                for ln in c.loans
            ]
    return base


@bp.get("/works/<work_id>")
def get_work(work_id):
    s = Session()
    w = s.get(m.Work, work_id)
    if not w:
        return jsonify(error="not found"), 404
    return jsonify(_work_json_full(w))


@bp.get("/books/find")
def find_existing():
    """Do I already own this? Match by ISBN (strongest) and/or title(+author).
    Returns the matching works (full record) so the Add flow can warn with shelf
    locations and any e-book versions before a duplicate is created."""
    from .lookup import normalise_isbn
    s = Session()
    isbn = (request.args.get("isbn") or "").strip()
    title = (request.args.get("title") or "").strip()
    author = (request.args.get("author") or "").strip()
    out, seen = [], set()

    def add(w):
        if w and w.id not in seen:
            seen.add(w.id)
            out.append(w)

    n = normalise_isbn(isbn)
    if n:
        for e in s.query(m.Edition).filter((m.Edition.isbn13 == n) | (m.Edition.isbn10 == n)).all():
            add(e.work)
    if title:
        rows = s.query(m.Work).filter(func.lower(m.Work.title) == title.lower()).all()
        for w in rows:
            if author:
                names = [c.author.canonical_name.lower() for c in w.contributors] + \
                        [c.author.sort_name.lower() for c in w.contributors]
                al = author.lower()
                if not any(al in nm or nm in al for nm in names):
                    continue
            add(w)
    return jsonify(matches=[_work_json_full(w) for w in out])


@bp.get("/dashboard")
def dashboard():
    """Aggregates for the stats/valuation dashboard."""
    import re as _re
    from collections import Counter
    s = Session()

    def grp(col):
        return [{"label": (k if k is not None else "—"), "count": n}
                for k, n in s.query(col, func.count()).group_by(col).order_by(func.count().desc()).all()]

    copies_total = s.query(m.Copy).count()
    with_sess = s.query(func.count(func.distinct(m.ReadingSession.copy_id))).scalar() or 0
    read = s.query(func.count()).select_from(m.ReadingSession).filter(m.ReadingSession.status == "read").scalar() or 0
    reading = s.query(func.count()).select_from(m.ReadingSession).filter(m.ReadingSession.status == "reading").scalar() or 0

    years = [y for (y,) in s.query(m.Edition.published_year).filter(m.Edition.published_year.isnot(None))]
    decades = [{"label": f"{d}s", "count": n} for d, n in sorted(Counter((y // 10) * 10 for y in years).items())]

    areas = Counter()
    for loc, n in s.query(m.Copy.location, func.count()).filter(m.Copy.location.isnot(None)).group_by(m.Copy.location):
        areas[_re.sub(r"\s*\d+\s*$", "", loc).strip() or loc] += n

    tags = [{"label": t, "count": n} for t, n in
            s.query(m.Tag.name, func.count(m.WorkTag.id)).join(m.WorkTag, m.WorkTag.tag_id == m.Tag.id)
            .group_by(m.Tag.name).order_by(func.count(m.WorkTag.id).desc()).limit(12).all()]
    pubs = [{"label": p, "count": n} for p, n in
            s.query(m.Edition.publisher, func.count()).filter(m.Edition.publisher.isnot(None))
            .group_by(m.Edition.publisher).order_by(func.count().desc()).limit(12).all()]

    list_value = [{"currency": c or "?", "total": round(float(t), 2)} for c, t in
                  s.query(m.Edition.list_price_currency, func.sum(m.Edition.list_price))
                  .filter(m.Edition.list_price.isnot(None)).group_by(m.Edition.list_price_currency).all()]
    valuation_total = float(s.query(func.sum(m.Copy.current_value)).scalar() or 0)

    return jsonify(
        totals={"works": s.query(m.Work).count(), "editions": s.query(m.Edition).count(),
                "copies": copies_total, "authors": s.query(m.Author).count(),
                "wishlist": s.query(m.WishlistItem).count(), "collections": s.query(m.Collection).count()},
        reading={"read": read, "reading": reading, "unread": max(copies_total - with_sess, 0)},
        by_kind=grp(m.Copy.kind), by_copy_type=grp(m.Copy.copy_type), by_condition=grp(m.Copy.condition),
        decades=decades, by_area=[{"label": a, "count": n} for a, n in areas.most_common(15)],
        top_genres=tags, top_publishers=pubs,
        list_value=list_value, valuation_total=round(valuation_total, 2),
    )


def _valuate(d):
    from .valuation import expected_value, BookInputs
    bi = BookInputs(
        market_price=float(d.get("market_price", 0)),
        horizon_years=float(d.get("horizon_years", 10)),
        condition=float(d.get("condition", 1.0)),
        provenance=float(d.get("provenance", 1.0)),
        platform=float(d.get("platform", 1.0)),
        library_holdings=(int(d["library_holdings"]) if d.get("library_holdings") not in (None, "") else None),
    )
    bi.validate()
    r = expected_value(bi)
    return {"expected_value": round(r.expected_value, 2),
            "range_low": round(getattr(r, "range_low", r.expected_value), 2),
            "range_high": round(getattr(r, "range_high", r.expected_value), 2)}


@bp.post("/valuate")
def valuate_endpoint():
    try:
        return jsonify(_valuate(request.get_json(silent=True) or {}))
    except (ValueError, TypeError) as e:
        return jsonify(error=str(e)), 400


@bp.post("/copies/<copy_id>/value")
def copy_value(copy_id):
    """Estimate (via the valuation engine) and SAVE a copy's current_value."""
    s = Session()
    c = s.get(m.Copy, copy_id)
    if not c:
        return jsonify(error="not found"), 404
    d = request.get_json(silent=True) or {}
    try:
        res = _valuate(d)
    except (ValueError, TypeError) as e:
        return jsonify(error=str(e)), 400
    c.current_value = res["expected_value"]
    c.current_value_currency = d.get("currency") or "GBP"
    s.commit()
    return jsonify(current_value=float(c.current_value), currency=c.current_value_currency, **res)


@bp.post("/works/<work_id>")
def update_work(work_id):
    """Edit a book (flat: work + first/selected edition + first/selected copy)."""
    s = Session()
    data = request.get_json(silent=True) or {}
    work = catalog.update_book(s, work_id, data)
    if not work:
        return jsonify(error="not found"), 404
    return jsonify(_work_json(work))


@bp.delete("/works/<work_id>")
def delete_work(work_id):
    s = Session()
    w = s.get(m.Work, work_id)
    if not w:
        return jsonify(error="not found"), 404
    s.delete(w)
    s.commit()
    return jsonify(ok=True)


@bp.post("/copies/<copy_id>/reading")
def set_reading(copy_id):
    """Set a copy's reading status: unread | reading | read (+ optional dates/progress)."""
    import datetime as dt
    s = Session()
    c = s.get(m.Copy, copy_id)
    if not c:
        return jsonify(error="not found"), 404
    data = request.get_json(silent=True) or {}
    st = data.get("status", "read")
    if st not in ("unread", "reading", "read"):
        return jsonify(error="status must be unread|reading|read"), 400
    if st == "unread":
        for r in list(c.reading_sessions):
            s.delete(r)
        s.commit()
        return jsonify(ok=True, status="unread")

    def _d(v):
        try:
            return dt.datetime.strptime(v[:10], "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return None
    rs = c.reading_sessions[0] if c.reading_sessions else None
    if not rs:
        rs = m.ReadingSession(copy_id=c.id)
        s.add(rs)
    rs.status = st
    if data.get("started"):
        rs.started = _d(data["started"])
    if data.get("finished"):
        rs.finished = _d(data["finished"])
    if st == "read" and not rs.finished:
        rs.finished = dt.date.today()
    if data.get("progress_pct") is not None:
        try:
            rs.progress_pct = int(data["progress_pct"])
        except (TypeError, ValueError):
            pass
    s.commit()
    return jsonify(ok=True, status=st)


@bp.delete("/copies/<copy_id>")
def delete_copy(copy_id):
    """Delete a single copy; if it was the work's last copy, delete the now-empty work too."""
    s = Session()
    c = s.get(m.Copy, copy_id)
    if not c:
        return jsonify(error="not found"), 404
    work = c.edition.work
    s.delete(c)
    s.flush()
    remaining = s.query(m.Copy).join(m.Edition).filter(m.Edition.work_id == work.id).count()
    if remaining == 0:
        s.delete(work)
    s.commit()
    return jsonify(ok=True, work_deleted=(remaining == 0))


@bp.get("/stats")
def stats():
    s = Session()
    return jsonify(
        works=s.query(m.Work).count(),
        editions=s.query(m.Edition).count(),
        copies=s.query(m.Copy).count(),
        authors=s.query(m.Author).count(),
        wishlist=s.query(m.WishlistItem).count(),
    )


# ------------------------------------------------------------- add a book
@bp.get("/lookup")
def lookup():
    """ISBN -> metadata (OpenLibrary + Google Books). Used by the add-by-ISBN/scan flows."""
    isbn = request.args.get("isbn", "")
    meta = isbn_lookup(isbn)
    if not meta:
        return jsonify(error="No metadata found for that ISBN"), 404
    return jsonify(meta)


@bp.post("/decode")
def decode():
    """Photo -> ISBN. Multipart 'image'. The barcode need only be visible and in focus."""
    from .barcode import decode_isbn_from_image
    f = request.files.get("image")
    if not f:
        return jsonify(error="No image uploaded"), 400
    isbn = decode_isbn_from_image(f.read())
    if not isbn:
        return jsonify(error="No barcode found in image"), 422
    return jsonify(isbn=isbn)


@bp.post("/books")
def add_book():
    """Add a book to the LIBRARY (creates/attaches Work -> Edition -> Copy)."""
    s = Session()
    data = request.get_json(silent=True) or {}
    if not (data.get("title") or "").strip():
        return jsonify(error="title is required"), 400
    work, edition, copy = catalog.add_book(s, data)
    return jsonify(work=_work_json(work), edition_id=edition.id, copy_id=copy.id), 201


# ------------------------------------------------------------- collections
@bp.get("/collections")
def collections_list():
    s = Session()
    kind = request.args.get("kind")
    q = s.query(m.Collection)
    if kind:
        q = q.filter(m.Collection.kind == kind)
    out = []
    for col in q.order_by(m.Collection.name):
        if col.kind == "wishlist":
            cnt = s.query(m.WishlistItem).filter(m.WishlistItem.collection_id == col.id).count()
        else:
            cnt = s.query(m.CollectionWork).filter(m.CollectionWork.collection_id == col.id).count()
        out.append({"id": col.id, "name": col.name, "kind": col.kind, "count": cnt})
    return jsonify(collections=out)


@bp.post("/collections")
def collections_add():
    s = Session()
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    kind = data.get("kind")
    if not name or kind not in ("library", "wishlist"):
        return jsonify(error="name and kind (library|wishlist) required"), 400
    if s.query(m.Collection).filter_by(name=name, kind=kind).first():
        return jsonify(error="collection already exists"), 409
    col = m.Collection(name=name, kind=kind)
    s.add(col)
    s.commit()
    return jsonify(id=col.id, name=col.name, kind=col.kind), 201


@bp.delete("/collections/<cid>")
def collections_delete(cid):
    s = Session()
    col = s.get(m.Collection, cid)
    if col:
        if col.kind == "wishlist":
            for it in s.query(m.WishlistItem).filter_by(collection_id=cid):
                it.collection_id = None
        s.delete(col)
        s.commit()
    return jsonify(ok=True)


@bp.post("/collections/<cid>/works")
def collection_add_work(cid):
    s = Session()
    wid = (request.get_json(silent=True) or {}).get("work_id")
    if not s.get(m.Collection, cid) or not s.get(m.Work, wid):
        return jsonify(error="not found"), 404
    if not s.query(m.CollectionWork).filter_by(collection_id=cid, work_id=wid).first():
        s.add(m.CollectionWork(collection_id=cid, work_id=wid))
        s.commit()
    return jsonify(ok=True)


@bp.delete("/collections/<cid>/works/<wid>")
def collection_remove_work(cid, wid):
    s = Session()
    cw = s.query(m.CollectionWork).filter_by(collection_id=cid, work_id=wid).first()
    if cw:
        s.delete(cw)
        s.commit()
    return jsonify(ok=True)


@bp.get("/wishlist")
def list_wishlist():
    s = Session()
    q = s.query(m.WishlistItem)
    cid = request.args.get("collection_id")
    if cid:
        q = q.filter(m.WishlistItem.collection_id == cid)
    items = q.order_by(m.WishlistItem.created_at.desc()).all()
    return jsonify(items=[
        {"id": w.id, "title": w.title, "target_price": float(w.target_price) if w.target_price else None,
         "currency": w.currency, "priority": w.priority, "notes": w.notes, "collection_id": w.collection_id}
        for w in items
    ])


@bp.post("/wishlist/<item_id>")
def update_wishlist(item_id):
    """Assign a wishlist item to a collection (or null)."""
    s = Session()
    it = s.get(m.WishlistItem, item_id)
    if not it:
        return jsonify(error="not found"), 404
    data = request.get_json(silent=True) or {}
    if "collection_id" in data:
        it.collection_id = data["collection_id"] or None
    s.commit()
    return jsonify(ok=True)


@bp.post("/wishlist")
def add_wishlist():
    """Add a wanted book (e.g. one you spotted in a shop) to the WISHLIST."""
    s = Session()
    data = request.get_json(silent=True) or {}
    if not (data.get("title") or "").strip():
        return jsonify(error="title is required"), 400
    item = catalog.add_wishlist(s, data)
    return jsonify(id=item.id, title=item.title), 201


@bp.delete("/wishlist/<item_id>")
def del_wishlist(item_id):
    s = Session()
    item = s.get(m.WishlistItem, item_id)
    if item:
        s.delete(item)
        s.commit()
    return jsonify(ok=True)


# ------------------------------------------------------------- user management (admin)
ROLES = {"admin", "consumer", "user", "readonly"}   # new: admin|consumer; legacy tolerated


def _admin_count(s, exclude_id=None):
    q = s.query(m.User).filter(m.User.role == "admin")
    if exclude_id:
        q = q.filter(m.User.id != exclude_id)
    return q.count()


@bp.get("/users")
def users_list():
    if not is_admin():
        return jsonify(error="admin only"), 403
    s = Session()
    return jsonify(users=[
        {"id": u.id, "username": u.username, "role": u.role}
        for u in s.query(m.User).order_by(m.User.username)
    ])


@bp.post("/users")
def users_create():
    if not is_admin():
        return jsonify(error="admin only"), 403
    s = Session()
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    role = data.get("role") or "user"
    if not username or len(password) < 6 or role not in ROLES:
        return jsonify(error="username, password (≥6 chars) and a valid role are required"), 400
    if s.query(m.User).filter(m.User.username == username).first():
        return jsonify(error="username already exists"), 409
    u = m.User(username=username, password_hash=hash_password(password), role=role)
    s.add(u)
    s.commit()
    return jsonify(id=u.id, username=u.username, role=u.role), 201


@bp.post("/users/<uid>")
def users_update(uid):
    """Admin: change a user's role and/or reset their password."""
    if not is_admin():
        return jsonify(error="admin only"), 403
    s = Session()
    u = s.get(m.User, uid)
    if not u:
        return jsonify(error="not found"), 404
    data = request.get_json(silent=True) or {}
    new_role = data.get("role")
    if new_role:
        if new_role not in ROLES:
            return jsonify(error="invalid role"), 400
        if u.role == "admin" and new_role != "admin" and _admin_count(s, exclude_id=u.id) == 0:
            return jsonify(error="cannot demote the last admin"), 400
        u.role = new_role
    if data.get("password"):
        if len(data["password"]) < 6:
            return jsonify(error="password must be ≥6 chars"), 400
        u.password_hash = hash_password(data["password"])
    s.commit()
    return jsonify(id=u.id, username=u.username, role=u.role)


@bp.delete("/users/<uid>")
def users_delete(uid):
    if not is_admin():
        return jsonify(error="admin only"), 403
    s = Session()
    u = s.get(m.User, uid)
    if not u:
        return jsonify(error="not found"), 404
    if u.id == session.get("uid"):
        return jsonify(error="you cannot delete your own account"), 400
    if u.role == "admin" and _admin_count(s, exclude_id=u.id) == 0:
        return jsonify(error="cannot delete the last admin"), 400
    s.delete(u)
    s.commit()
    return jsonify(ok=True)


@bp.get("/export/library.csv")
def export_library():
    """Download the whole library as UTF-8 CSV (BOM; Greek-safe). One row per copy."""
    from .export import library_csv
    from .backup import timestamp
    return Response(library_csv(Session()), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename=library-{timestamp()}.csv"})


@bp.get("/export/wishlist.csv")
def export_wishlist():
    """Download the wishlist as UTF-8 CSV (BOM; Greek-safe)."""
    from .export import wishlist_csv
    from .backup import timestamp
    return Response(wishlist_csv(Session()), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename=wishlist-{timestamp()}.csv"})


@bp.get("/stats/data-dictionary.csv")
def export_data_dictionary():
    """Download a per-database, per-column data dictionary (descriptions + profiling
    metrics) as UTF-8 CSV (BOM; Greek-safe)."""
    from .datadictionary import csv_bytes
    from .backup import timestamp
    return Response(csv_bytes(Session()), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename=data-dictionary-{timestamp()}.csv"})


@bp.get("/stats/data-dictionary")
def data_dictionary_json():
    """The same data dictionary as JSON, for the in-app grid under the Stats tab."""
    from .datadictionary import dictionary_rows, _CSV_FIELDS
    return jsonify(columns=_CSV_FIELDS, rows=dictionary_rows(Session()))


@bp.get("/backup/database.sql")
def backup_database():
    """Admin: full Postgres dump (authoritative restore)."""
    if not is_admin():
        return jsonify(error="admin only"), 403
    from .backup import database_sql, timestamp
    try:
        data = database_sql()
    except Exception as e:
        return jsonify(error=f"pg_dump failed: {e}"), 500
    return Response(data, mimetype="application/sql",
                    headers={"Content-Disposition": f"attachment; filename=loa-db-{timestamp()}.sql"})


@bp.get("/backup/full.zip")
def backup_full():
    """Admin: portable archive — CSVs + thumbnails + db dump + linking manifest + README."""
    if not is_admin():
        return jsonify(error="admin only"), 403
    from flask import after_this_request
    from .backup import write_full_zip, timestamp
    import os
    path = write_full_zip(Session())

    @after_this_request
    def _cleanup(resp):
        try:
            os.remove(path)
        except OSError:
            pass
        return resp

    return send_file(path, mimetype="application/zip", as_attachment=True,
                     download_name=f"loa-full-{timestamp()}.zip")


# ------------------------------------------------------- settings + folder browser
@bp.get("/settings")
def get_settings():
    """Expose the user-configurable settings (e-book folder + chosen skin)."""
    from .settings import get_ebooks_dir, get_setting
    root = get_ebooks_dir()
    return jsonify(ebooks_dir=root or None, ebooks_dir_exists=bool(root) and os.path.isdir(root),
                   skin=get_setting("skin") or None)


@bp.post("/settings")
def update_settings():
    """Admin: set the e-book folder path (stored in the DB, not hardcoded)."""
    if not is_admin():
        return jsonify(error="admin only"), 403
    from .settings import set_setting, get_ebooks_dir, get_setting
    from .browse import allowed_roots
    body = request.get_json(silent=True) or {}
    if "skin" in body:
        skin = (body.get("skin") or "").strip()
        if skin:
            set_setting("skin", skin)
        if "ebooks_dir" not in body:
            return jsonify(skin=get_setting("skin") or None)
    if "ebooks_dir" in body:
        path = (body.get("ebooks_dir") or "").strip()
        if path:
            real = os.path.realpath(path)
            if not os.path.isdir(real):
                return jsonify(error="that path is not a folder on the server"), 400
            roots = allowed_roots()
            if roots and not any(
                _safe_commonpath(real, r) for r in roots
            ):
                return jsonify(error=f"folder must be inside an allowed root ({', '.join(roots)})"), 400
            set_setting("ebooks_dir", real)
        else:
            set_setting("ebooks_dir", "")
    return jsonify(ebooks_dir=get_ebooks_dir() or None)


def _safe_commonpath(path, root):
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:
        return False


@bp.post("/browse")
def browse():
    """List server folders/files under an allowed root, for the in-app path picker."""
    from .browse import list_dir
    body = request.get_json(silent=True) or {}
    try:
        return jsonify(list_dir(body.get("path") or None))
    except NotADirectoryError as e:
        return jsonify(error=str(e)), 400


# ------------------------------------------------------- E-book folder scan
@bp.get("/ebooks/status")
def ebooks_status():
    """Is an e-book folder configured/reachable, and how many e-book copies are cataloged?"""
    from .settings import get_ebooks_dir
    root = get_ebooks_dir()
    configured = bool(root)
    exists = bool(root) and os.path.isdir(root)
    count = Session().query(m.Copy).filter(m.Copy.kind == "ebook").count()
    return jsonify(configured=configured, exists=exists, root=root or None, ebook_copies=count)


@bp.post("/ebooks/scan")
def ebooks_scan():
    """Admin: scan the e-book folder and catalog any new files (idempotent)."""
    if not is_admin():
        return jsonify(error="admin only"), 403
    body = request.get_json(silent=True) or {}
    from .ebookscan import scan_folder
    try:
        stats = scan_folder(Session(), root=body.get("root") or None,
                            lookup=bool(body.get("lookup")))
    except NotADirectoryError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:  # surface unexpected problems cleanly
        return jsonify(error=f"scan failed: {e}"), 500
    return jsonify(stats)


@bp.get("/ebooks/file/<copy_id>")
def ebooks_file(copy_id):
    """Stream an e-book file for download/open. Path-guarded to within EBOOKS_DIR."""
    from .settings import get_ebooks_dir
    c = Session().get(m.Copy, copy_id)
    if not c or not c.file_ref:
        return jsonify(error="no file for this copy"), 404
    path = os.path.realpath(c.file_ref)
    ebooks_dir = get_ebooks_dir()
    root = os.path.realpath(ebooks_dir) if ebooks_dir else None
    # Never serve a path outside the configured e-book folder.
    if not root or not _safe_commonpath(path, root):
        return jsonify(error="file is outside the configured e-book folder"), 403
    if not os.path.isfile(path):
        return jsonify(error="file not found on disk"), 404
    return send_file(path, as_attachment=True, download_name=os.path.basename(path))


# ------------------------------------------------------------- library maps (3D)
def _ensure_default_maps(s):
    if s.query(m.LibraryMap).count() == 0:
        s.add(m.LibraryMap(area="Home", name="Home Library",
                           asset_path="/static/maps/demo-room/index.html"))
        s.commit()


@bp.get("/maps")
def maps_list():
    s = Session()
    _ensure_default_maps(s)
    return jsonify(maps=[
        {"id": x.id, "area": x.area, "name": x.name, "asset_path": x.asset_path}
        for x in s.query(m.LibraryMap).order_by(m.LibraryMap.area)
    ])


@bp.post("/maps")
def maps_add():
    """Admin: add/replace a map for an area. Either upload an HTML file or pass asset_path."""
    if not is_admin():
        return jsonify(error="admin only"), 403
    s = Session()
    if request.files.get("file"):
        from werkzeug.utils import secure_filename
        area = (request.form.get("area") or "").strip()
        name = (request.form.get("name") or area).strip()
        f = request.files["file"]
        if not area:
            return jsonify(error="area required"), 400
        d = os.path.join(current_app.static_folder, "maps")
        os.makedirs(d, exist_ok=True)
        fn = secure_filename(f"{area}.html") or "map.html"
        f.save(os.path.join(d, fn))
        asset = f"/static/maps/{fn}"
    else:
        data = request.get_json(silent=True) or {}
        area = (data.get("area") or "").strip()
        name = (data.get("name") or area).strip()
        asset = (data.get("asset_path") or "").strip()
    if not area or not asset:
        return jsonify(error="area and asset (file or asset_path) required"), 400
    existing = s.query(m.LibraryMap).filter(m.LibraryMap.area == area).first()
    if existing:
        existing.name, existing.asset_path = name, asset
    else:
        s.add(m.LibraryMap(area=area, name=name, asset_path=asset))
    s.commit()
    return jsonify(ok=True), 201


@bp.delete("/maps/<map_id>")
def maps_delete(map_id):
    if not is_admin():
        return jsonify(error="admin only"), 403
    s = Session()
    x = s.get(m.LibraryMap, map_id)
    if x:
        s.delete(x)
        s.commit()
    return jsonify(ok=True)


@bp.post("/editions/<edition_id>/cover")
def upload_cover(edition_id):
    """Admin: set an edition's cover from an uploaded image file or a camera photo
    (multipart 'file'). Stored in the DB like web covers (offline + backup-portable)."""
    if not is_admin():
        return jsonify(error="admin only"), 403
    s = Session()
    e = s.get(m.Edition, edition_id)
    if not e:
        return jsonify(error="not found"), 404
    f = request.files.get("file")
    if not f:
        return jsonify(error="no file uploaded"), 400
    ct = (f.mimetype or "").lower()
    if not ct.startswith("image/"):
        return jsonify(error="file must be an image"), 400
    data = f.read(8 * 1024 * 1024 + 1)
    from .covers import store_cover_bytes
    if not store_cover_bytes(s, e, data, ct, source="upload"):
        return jsonify(error="image is empty or larger than 8 MiB"), 400
    s.commit()
    return jsonify(ok=True, cover_path=e.cover_path)


@bp.delete("/editions/<edition_id>/cover")
def delete_cover(edition_id):
    """Admin: remove an edition's cover (deletes the stored DB image if any, and clears
    the cover reference so no cover shows)."""
    if not is_admin():
        return jsonify(error="admin only"), 403
    s = Session()
    e = s.get(m.Edition, edition_id)
    if not e:
        return jsonify(error="not found"), 404
    ci = s.get(m.CoverImage, edition_id)
    if ci:
        s.delete(ci)
    e.cover_path = None
    s.commit()
    return jsonify(ok=True)


@bp.get("/cover/db/<edition_id>")
def cover_db(edition_id):
    """Serve a web-fetched cover stored in the DB (offline-safe, backup-portable)."""
    ci = Session().get(m.CoverImage, edition_id)
    if not ci or not ci.data:
        return jsonify(error="not found"), 404
    return send_file(io.BytesIO(ci.data), mimetype=ci.content_type or "image/jpeg")


@bp.get("/cover/<legacy_uuid>")
def cover(legacy_uuid):
    """Serve a migrated cover straight from the .bcbk backup (read-only)."""
    safe = "".join(c for c in legacy_uuid if c.isalnum())
    path = os.path.join(Config.DATA_DIR, Config.BACKUP_BCBK)
    if not os.path.exists(path):
        return jsonify(error="no backup"), 404
    try:
        with tarfile.open(path) as tf:
            data = tf.extractfile(f"{safe}.jpg").read()
    except (KeyError, OSError):
        return jsonify(error="not found"), 404
    return send_file(io.BytesIO(data), mimetype="image/jpeg")


# ----------------------------------------------------------------- enrichment
@bp.post("/enrichment/dry-run")
def enrich_dry_run():
    """Start a dry run. Body (optional): {"edition_ids": [...], "note": "..."}.
    Writes NOTHING to your records — only proposals for review."""
    s = Session()
    body = request.get_json(silent=True) or {}
    run = enrichment.dry_run(s, edition_ids=body.get("edition_ids"), note=body.get("note"))
    return jsonify(enrichment.diff(s, run.id)), 201


@bp.get("/discover/status")
def discover_status():
    """Whether the TALPA 'describe a book' discovery is configured."""
    return jsonify(configured=bool(Config.LIBRARYTHING_TALPA_TOKEN))


@bp.post("/discover")
def discover():
    """Admin: natural-language 'describe a book' via TALPA. Body: {"query": "..."}.
    Each result is flagged owned_work_id if its ISBN matches a book you already have."""
    if not is_admin():
        return jsonify(error="admin only"), 403
    q = ((request.get_json(silent=True) or {}).get("query") or "").strip()
    from .talpa import describe
    res = describe(q)
    if not res["ok"]:
        return jsonify(error=res["error"]), 400
    s = Session()
    all_isbns = {i for c in res["results"] for i in c["isbns"]}
    owned = {}
    if all_isbns:
        for ed in s.query(m.Edition).filter(m.Edition.isbn13.in_(all_isbns)).all():
            owned.setdefault(ed.isbn13, ed.work_id)
    for c in res["results"]:
        c["owned_work_id"] = next((owned[i] for i in c["isbns"] if i in owned), None)
    return jsonify(results=res["results"], remaining=res.get("remaining"))


@bp.get("/enrichment/match-sources")
def enrich_match_sources():
    """Admin: the sources the Find-match picker can search."""
    if not is_admin():
        return jsonify(error="admin only"), 403
    from .titlesearch import available
    return jsonify(sources=available())


def _slugify(name):
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s or "src"


@bp.get("/sources/custom")
def custom_sources_list():
    """Admin: user-added SRU catalogue sources."""
    if not is_admin():
        return jsonify(error="admin only"), 403
    from .settings import get_setting
    return jsonify(sources=get_setting("custom_sources") or [])


@bp.post("/sources/custom")
def custom_sources_add():
    """Admin: add an SRU catalogue. Body: {name, url} (url is an SRU template with {q})."""
    if not is_admin():
        return jsonify(error="admin only"), 403
    from .settings import get_setting, set_setting
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    url = (body.get("url") or "").strip()
    if not name or not url:
        return jsonify(error="name and url are required"), 400
    if "{q}" not in url:
        return jsonify(error="url must contain {q} where the search term goes"), 400
    if not (url.startswith("http://") or url.startswith("https://")):
        return jsonify(error="url must start with http:// or https://"), 400
    sources = get_setting("custom_sources") or []
    keys = {s["key"] for s in sources}
    base = _slugify(name)
    key = base
    i = 2
    while key in keys:
        key = f"{base}-{i}"; i += 1
    sources.append({"key": key, "name": name, "url": url})
    set_setting("custom_sources", sources)
    return jsonify(ok=True, key=key, sources=sources)


@bp.delete("/sources/custom/<key>")
def custom_sources_delete(key):
    if not is_admin():
        return jsonify(error="admin only"), 403
    from .settings import get_setting, set_setting
    sources = [s for s in (get_setting("custom_sources") or []) if s.get("key") != key]
    set_setting("custom_sources", sources)
    return jsonify(ok=True, sources=sources)


@bp.post("/enrichment/match-search")
def enrich_match_search():
    """Admin: free-text title/author search across selected sources → candidate records to
    pick from (for books with no ISBN). Body: {"query": "...", "sources": ["biblionet", ...]}."""
    if not is_admin():
        return jsonify(error="admin only"), 403
    body = request.get_json(silent=True) or {}
    q = (body.get("query") or "").strip()
    if not q:
        return jsonify(error="empty query"), 400
    from .titlesearch import search
    return jsonify(candidates=search(body.get("sources"), q))


@bp.post("/enrichment/apply-match")
def enrich_apply_match():
    """Admin: apply a user-chosen candidate to an edition (fills gaps + cover + ISBN).
    Body: {"edition_id": "...", "candidate": {...}}."""
    if not is_admin():
        return jsonify(error="admin only"), 403
    body = request.get_json(silent=True) or {}
    applied = enrichment.apply_candidate(
        Session(), body.get("edition_id"), body.get("candidate") or {},
        update_title=bool(body.get("update_title")),
        add_author_forms=bool(body.get("add_author_forms")),
    )
    if applied is None:
        return jsonify(error="edition not found"), 404
    return jsonify(ok=True, applied=applied)


@bp.get("/enrichment/runs/<run_id>")
def enrich_get(run_id):
    """Review the diff (proposals: add/change, current vs proposed)."""
    s = Session()
    d = enrichment.diff(s, run_id)
    return (jsonify(d), 200) if d else (jsonify(error="not found"), 404)


@bp.post("/enrichment/runs/<run_id>/select")
def enrich_select(run_id):
    """Pick which proposals to commit. Body: {"proposal_ids": [...], "value": true}."""
    s = Session()
    body = request.get_json(silent=True) or {}
    enrichment.select(s, run_id, body.get("proposal_ids", []), body.get("value", True))
    return jsonify(enrichment.diff(s, run_id))


@bp.get("/enrichment/sources")
def sources_list():
    """List enrichment sources (admin). `fetchable` = whether a built-in fetcher exists."""
    if not is_admin():
        return jsonify(error="admin only"), 403
    from .lookup import ensure_default_sources, FETCHERS
    s = Session()
    ensure_default_sources(s)
    rows = s.query(m.EnrichmentSource).order_by(m.EnrichmentSource.priority).all()
    return jsonify(available=sorted(FETCHERS.keys()), sources=[
        {"id": r.id, "key": r.key, "name": r.name, "enabled": r.enabled,
         "priority": r.priority, "fetchable": r.key in FETCHERS}
        for r in rows
    ])


@bp.post("/enrichment/sources")
def sources_add():
    if not is_admin():
        return jsonify(error="admin only"), 403
    s = Session()
    data = request.get_json(silent=True) or {}
    key = (data.get("key") or "").strip()
    if not key:
        return jsonify(error="key required"), 400
    if s.query(m.EnrichmentSource).filter(m.EnrichmentSource.key == key).first():
        return jsonify(error="source already exists"), 409
    src = m.EnrichmentSource(key=key, name=(data.get("name") or key),
                             enabled=bool(data.get("enabled", True)),
                             priority=int(data.get("priority", 100)))
    s.add(src)
    s.commit()
    return jsonify(id=src.id), 201


@bp.post("/enrichment/sources/<sid>")
def sources_update(sid):
    if not is_admin():
        return jsonify(error="admin only"), 403
    s = Session()
    src = s.get(m.EnrichmentSource, sid)
    if not src:
        return jsonify(error="not found"), 404
    data = request.get_json(silent=True) or {}
    if "enabled" in data:
        src.enabled = bool(data["enabled"])
    if "priority" in data:
        src.priority = int(data["priority"])
    if "name" in data:
        src.name = data["name"]
    s.commit()
    return jsonify(ok=True)


@bp.delete("/enrichment/sources/<sid>")
def sources_delete(sid):
    if not is_admin():
        return jsonify(error="admin only"), 403
    s = Session()
    src = s.get(m.EnrichmentSource, sid)
    if src:
        s.delete(src)
        s.commit()
    return jsonify(ok=True)


@bp.post("/enrichment/runs/<run_id>/commit")
def enrich_commit(run_id):
    """Apply. Body: {"mode": "selected" | "all" | "none"}.
    selected=picked records, all=enrich everything, none=do nothing (discard)."""
    s = Session()
    mode = (request.get_json(silent=True) or {}).get("mode", "selected")
    if mode not in ("selected", "all", "none"):
        return jsonify(error="mode must be selected|all|none"), 400
    result = enrichment.commit(s, run_id, mode=mode)
    return (jsonify(result), 200) if result else (jsonify(error="not found"), 404)
