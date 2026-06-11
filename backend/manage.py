#!/usr/bin/env python3
"""
Management CLI.

  python manage.py initdb              create tables
  python manage.py import              load MASTER CSV -> DB (offline, idempotent)
  python manage.py stats               print catalog counts
  python manage.py enrich-dry          start a dry run, print the diff (no writes)
  python manage.py enrich-commit RUN --mode selected|all|none

Network enrichment is opt-in and never triggered by import.
"""
import argparse
import json
import os
import sys

from app.db import Session, init_db
from app import models as m
from app.importer import Importer
from app import enrichment


def cmd_initdb(args):
    init_db()
    print("tables created")


def cmd_import(args):
    s = Session()
    stats = Importer(session=s).run()
    print("import complete:", json.dumps(stats, ensure_ascii=False))


def cmd_stats(args):
    s = Session()
    print(json.dumps({
        "works": s.query(m.Work).count(),
        "editions": s.query(m.Edition).count(),
        "copies": s.query(m.Copy).count(),
        "authors": s.query(m.Author).count(),
    }, ensure_ascii=False))


def cmd_enrich_dry(args):
    s = Session()
    run = enrichment.dry_run(s, note=args.note)
    d = enrichment.diff(s, run.id)
    print(f"run {run.id}: {len(d['proposals'])} proposals")
    print(json.dumps(d, ensure_ascii=False, indent=2)[:4000])


def cmd_enrich_commit(args):
    s = Session()
    print(json.dumps(enrichment.commit(s, args.run_id, mode=args.mode), ensure_ascii=False))


def cmd_create_user(args):
    import getpass
    from app.auth import hash_password
    from app import models as m
    s = Session()
    if s.query(m.User).filter(m.User.username == args.username).first():
        print(f"user '{args.username}' already exists"); return
    pw = args.password or getpass.getpass(f"password for {args.username}: ")
    s.add(m.User(username=args.username, password_hash=hash_password(pw), role=args.role))
    s.commit()
    print(f"created user '{args.username}' (role={args.role})")


def cmd_ensure_admin(args):
    """Create a default admin only if there are no users yet. Prints generated password once."""
    import secrets as _secrets
    from app.auth import hash_password
    from app import models as m
    s = Session()
    if s.query(m.User).count() > 0:
        print("users already exist; not creating a default admin")
        return
    username = os.environ.get("LOA_ADMIN_USER", "admin")
    pw = os.environ.get("LOA_ADMIN_PASSWORD") or _secrets.token_urlsafe(12)
    s.add(m.User(username=username, password_hash=hash_password(pw), role="admin"))
    s.commit()
    print("=" * 56)
    print(f"  ADMIN ACCOUNT CREATED  user: {username}")
    print(f"                         pass: {pw}")
    print("  ^ save this; change it in-app or with: manage.py passwd")
    print("=" * 56)


def cmd_passwd(args):
    import getpass
    from app.auth import hash_password
    from app import models as m
    s = Session()
    u = s.query(m.User).filter(m.User.username == args.username).first()
    if not u:
        print(f"no such user: {args.username}"); return
    u.password_hash = hash_password(args.password or getpass.getpass("new password: "))
    s.commit()
    print(f"password updated for '{args.username}'")


def cmd_list_users(args):
    from app import models as m
    s = Session()
    for u in s.query(m.User).order_by(m.User.username):
        print(f"  {u.username:20s} {u.role}")


def cmd_reindex(args):
    from app.search import reindex
    s = Session()
    reindex(s)
    print("search index rebuilt for", s.query(m.Work).count(), "works")


def cmd_fix_mojibake(args):
    from app import mojibake
    s = Session()
    r = mojibake.scan(s)
    auto = len(r["plain"]) + len(r["merge"])
    print(f"auto-fixable: {auto}  |  residual (reported only): {len(r['residual'])}")
    if args.apply:
        print("applying…", mojibake.apply(s))
    else:
        print("dry-run — re-run with --apply to write. Residuals are not auto-changed.")


def cmd_export_csv(args):
    from app.export import library_csv, wishlist_csv
    s = Session()
    if args.stdout:
        sys.stdout.buffer.write(library_csv(s) if args.stdout == "library" else wishlist_csv(s))
        return
    os.makedirs(args.dir, exist_ok=True)
    with open(os.path.join(args.dir, "library.csv"), "wb") as f:
        f.write(library_csv(s))
    with open(os.path.join(args.dir, "wishlist.csv"), "wb") as f:
        f.write(wishlist_csv(s))
    print("wrote library.csv, wishlist.csv to", args.dir)


SAMPLE_BOOKS = [
    {"title": "Pride and Prejudice", "authors": ["Austen, Jane"], "isbn": "9780141439518",
     "publisher": "Penguin Classics", "year": "1813", "format": "Paperback", "language": "English",
     "tags": ["Classics", "Romance"],
     "description": "A comedy of manners following Elizabeth Bennet and Mr Darcy in Regency England. (Public domain.)",
     "copy": {"location": "Home 3", "kind": "physical", "copy_type": "reading", "condition": "used"}},
    {"title": "Frankenstein", "authors": ["Shelley, Mary"], "isbn": "9780486282114",
     "publisher": "Dover", "year": "1818", "format": "Paperback", "language": "English",
     "tags": ["Classics", "Gothic", "Science Fiction"],
     "description": "Victor Frankenstein creates a living being and must face the consequences. (Public domain.)",
     "copy": {"location": "Home 7", "kind": "physical", "copy_type": "reading", "condition": "used"}},
    {"title": "Moby-Dick", "authors": ["Melville, Herman"], "isbn": "9781503280786",
     "publisher": "CreateSpace", "year": "1851", "format": "Paperback", "language": "English",
     "tags": ["Classics", "Adventure"],
     "description": "Captain Ahab's obsessive hunt for the white whale. (Public domain.)",
     "copy": {"location": "Home 12", "kind": "physical", "copy_type": "reading", "condition": "used"}},
    {"title": "The Odyssey", "authors": ["Homer"], "isbn": "9780140268867",
     "publisher": "Penguin Classics", "year": "1996", "format": "Paperback", "language": "English",
     "tags": ["Classics", "Poetry", "Mythology"],
     "description": "Odysseus's long journey home after the Trojan War. (Public domain text.)",
     "copy": {"location": "Home 1", "kind": "physical", "copy_type": "reading", "condition": "used"}},
    {"title": "Dracula", "authors": ["Stoker, Bram"], "isbn": "9780486411095",
     "publisher": "Dover", "year": "1897", "format": "Paperback", "language": "English",
     "tags": ["Classics", "Gothic", "Horror"],
     "description": "The classic vampire novel told through letters and journals. (Public domain.)",
     "copy": {"location": "Home 22", "kind": "physical", "copy_type": "reading", "condition": "used"}},
    {"title": "Great Expectations", "authors": ["Dickens, Charles"], "isbn": "9780141439563",
     "publisher": "Penguin Classics", "year": "1861", "format": "Paperback", "language": "English",
     "tags": ["Classics"],
     "description": "The coming-of-age of the orphan Pip. (Public domain.)",
     "copy": {"location": "Home 15", "kind": "physical", "copy_type": "reading", "condition": "used"}},
    {"title": "The Adventures of Sherlock Holmes", "authors": ["Doyle, Arthur Conan"], "isbn": "9780486474915",
     "publisher": "Dover", "year": "1892", "format": "Paperback", "language": "English",
     "tags": ["Classics", "Mystery"],
     "description": "Twelve short stories featuring the detective Sherlock Holmes. (Public domain.)",
     "copy": {"location": "Home 30", "kind": "physical", "copy_type": "reading", "condition": "used"}},
    {"title": "Meditations", "authors": ["Marcus Aurelius"], "isbn": "9780140449334",
     "publisher": "Penguin Classics", "year": "2006", "format": "Paperback", "language": "English",
     "tags": ["Classics", "Philosophy"],
     "description": "Personal writings of the Roman emperor on Stoic philosophy. (Public domain text.)",
     "copy": {"location": "Home 44", "kind": "physical", "copy_type": "reading", "condition": "used"}},
    {"title": "Alice's Adventures in Wonderland", "authors": ["Carroll, Lewis"], "isbn": "9780486275437",
     "publisher": "Dover", "year": "1865", "format": "Paperback", "language": "English",
     "tags": ["Classics", "Fantasy", "Children"],
     "description": "Alice falls down a rabbit-hole into a world of curious logic. (Public domain.)",
     "copy": {"location": "Home 9", "kind": "physical", "copy_type": "reading", "condition": "used"}},
    {"title": "The Republic", "authors": ["Plato"], "isbn": "9780140455113",
     "publisher": "Penguin Classics", "year": "2007", "format": "Paperback", "language": "English",
     "tags": ["Classics", "Philosophy"],
     "description": "A Socratic dialogue on justice and the ideal state. (Public domain text.)",
     "copy": {"location": "Home 5", "kind": "physical", "copy_type": "reading", "condition": "used"}},
]


def cmd_seed_sample(args):
    """Add a few public-domain example books so a fresh install isn't empty."""
    from app.catalog import add_book
    from app.search import reindex
    s = Session()
    existing = s.query(m.Work).count()
    if existing and not args.force:
        print(f"catalog already has {existing} works; skipping (use --force to add anyway)")
        return
    for b in SAMPLE_BOOKS:
        add_book(s, b)
    s.commit()
    reindex(s)
    print(f"seeded {len(SAMPLE_BOOKS)} public-domain sample books")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(required=True)
    sub.add_parser("initdb").set_defaults(func=cmd_initdb)
    sub.add_parser("import").set_defaults(func=cmd_import)
    ss = sub.add_parser("seed-sample"); ss.add_argument("--force", action="store_true")
    ss.set_defaults(func=cmd_seed_sample)
    sub.add_parser("stats").set_defaults(func=cmd_stats)
    d = sub.add_parser("enrich-dry"); d.add_argument("--note"); d.set_defaults(func=cmd_enrich_dry)
    c = sub.add_parser("enrich-commit")
    c.add_argument("run_id")
    c.add_argument("--mode", choices=["selected", "all", "none"], default="selected")
    c.set_defaults(func=cmd_enrich_commit)
    e = sub.add_parser("export-csv")
    e.add_argument("--dir", default="backups")
    e.add_argument("--stdout", choices=["library", "wishlist"], help="write one CSV to stdout")
    e.set_defaults(func=cmd_export_csv)
    cu = sub.add_parser("create-user")
    cu.add_argument("username")
    cu.add_argument("--role", choices=["admin", "user", "readonly"], default="user")
    cu.add_argument("--password", help="omit to be prompted")
    cu.set_defaults(func=cmd_create_user)
    sub.add_parser("ensure-admin").set_defaults(func=cmd_ensure_admin)
    pw = sub.add_parser("passwd"); pw.add_argument("username"); pw.add_argument("--password")
    pw.set_defaults(func=cmd_passwd)
    sub.add_parser("list-users").set_defaults(func=cmd_list_users)
    sub.add_parser("reindex").set_defaults(func=cmd_reindex)
    fm = sub.add_parser("fix-mojibake")
    fm.add_argument("--apply", action="store_true", help="write the fixes (default: dry-run report)")
    fm.set_defaults(func=cmd_fix_mojibake)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
