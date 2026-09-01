/*
 * references.tsx — the rail's RF slot: every reference sheet, one door.
 *
 * The workbench already renders a course's sheet, but reaching it costs
 * opening the workbench, opening a course, and switching the dock — a route
 * you take while studying, not while checking one equation mid-problem. This
 * view is the short way in.
 *
 * **Two levels.** Opening the view lands on a home, and the home is
 * deliberately a bare list — one row per *course*, its name and one door.
 * It briefly listed every reference flat, and before that carried the study
 * catalogue's cards with counts and gauges on each; but a course's material
 * belongs behind the course's own door, so the row says how many references
 * wait inside and the course page carries the navigation — the sheet with
 * its section pills, the imported notes as links above it. Nothing is
 * auto-opened: the last sheet you read is not the sheet you came for often
 * enough that guessing costs more than one click. Esc peels course → home →
 * closed, the workbench's own ladder, in the capture phase so App's ladder
 * only sees the last rung.
 *
 * Two families on purpose, mirroring GET /api/references: the contract's
 * `type: reference` sheets open here — the same `ReferenceDock` the
 * workbench mounts, same fetch, same tier toggle, so the two doors can never
 * disagree — while a course's other `*-reference.md` notes, imported
 * resources that share the name but not the grammar, open in Obsidian. The
 * row's right edge says which, so no click is a surprise.
 */
import { useEffect, useMemo, useState } from "react";
import { get, obsidianHref } from "./api";
import type { References } from "./api";
import ReferenceDock from "./reference";

export default function ReferencesView({ open, vault, onClose }: {
  open: boolean; vault: string; onClose: () => void;
}) {
  const [d, setD] = useState<References | null | undefined>(undefined);
  // null is the home. Deliberately not persisted: the last sheet you read is
  // a guess about what you came for, and the home exists to make the real
  // answer one click.
  const [sel, setSel] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setD(undefined);
    setSel(null);
    get<References>("references").then(setD).catch(() => setD(null));
  }, [open]);

  // Esc peels sheet → home in the capture phase; on the home it falls through
  // untouched to App's ladder, which closes the view. The workbench's own
  // pattern, and the `return` is its whole safety.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.repeat || e.ctrlKey || e.altKey || e.metaKey) return;
      if (e.key !== "Escape" || sel === null) return;
      setSel(null);
      e.preventDefault();
      e.stopPropagation();
    };
    document.addEventListener("keydown", onKey, true);
    return () => document.removeEventListener("keydown", onKey, true);
  }, [open, sel]);

  // Sheets first in the scan's order, then any course that only has extras —
  // the union orders the list, so nothing with material is unreachable.
  const courses = useMemo(() => {
    if (!d) return [];
    const seen = new Set<string>();
    const out: string[] = [];
    for (const r of [...d.sheets, ...d.extras]) {
      if (!seen.has(r.course)) { seen.add(r.course); out.push(r.course); }
    }
    return out;
  }, [d]);

  const selExtras = d?.extras.filter(e => e.course === sel) ?? [];

  if (!open) return null;

  return (
    <div className="palette-backdrop" onClick={onClose}>
      {/* Full-bleed like WORK and the calendar — a reference sheet is a
          reading surface, so the container paves the window (the office
          floats it as a sheet, enterprise.css) while the content keeps a
          readable column. */}
      <div className="refs-view" onClick={e => e.stopPropagation()}
           role="dialog" aria-label="References">
        <header className="study-head">
          {sel !== null && (
            <button className="wb-rail-back" onClick={() => setSel(null)}
                    title="All sheets (Esc)">‹ All sheets</button>
          )}
          <span className="label">
            ◇ REFERENCES — {sel !== null ? sel : "WHAT YOU LOOK UP"}
          </span>
          <button className="ghost" onClick={onClose} title="Close (Esc)">✕</button>
        </header>

        {d === undefined && <p className="dim pad">reading the sheets…</p>}
        {d === null && <p className="err pad">backend unreachable</p>}

        {/* §3.3 — the first screen at zero is the most designed one. The same
            empty pattern as the course grid, because it is the same moment. */}
        {d && courses.length === 0 && (
          <div className="wb-empty">
            <span className="empty-mark" aria-hidden="true">▤</span>
            <h2>No reference sheets yet.</h2>
            <p>
              A course's sheet is written from its own modules and assessments —
              one model call, one revertible commit, and it shows up here:
            </p>
            <p><code>sigma guide reference &lt;COURSE&gt;</code></p>
          </div>
        )}

        {d && courses.length > 0 && sel === null && (
          <div className="refs-body"><div className="refs-col">
            {/* One row per course — the course page carries everything past
                that door: the sheet with its own section nav, and the
                imported notes as links above it. The single exception is a
                course whose only reference is an imported note: routing that
                through a course page would be a hop to one link, so the row
                *is* that link. */}
            <ul className="refs-list">
              {courses.map(c => {
                const sheet = d.sheets.find(s => s.course === c) ?? null;
                const extras = d.extras.filter(e => e.course === c);
                const n = (sheet ? 1 : 0) + extras.length;
                if (!sheet && n === 1) {
                  const e = extras[0];
                  return (
                    <li key={c}>
                      <a className="refs-row" href={obsidianHref(vault, e.file)}
                         title={`${e.file} — opens in Obsidian`}>
                        <span className="refs-row-name">
                          <span className="refs-row-course">{c}</span>
                          {e.title}
                        </span>
                        <span className="refs-row-go">Obsidian<span aria-hidden="true"> ↗</span></span>
                      </a>
                    </li>
                  );
                }
                return (
                  <li key={c}>
                    <button className="refs-row" onClick={() => setSel(c)}
                            title={`open ${c}'s reference${n === 1 ? "" : "s"}`}>
                      <span className="refs-row-name">
                        <span className="refs-row-course">{c}</span>
                        {n === 1 ? "Reference sheet" : `${n} references`}
                        {/* Held is the one fact a bare row still owes you —
                            the problems themselves are shown inside. */}
                        {sheet && sheet.held > 0 && (
                          <span className="refs-row-held"
                                title={`the sheet fails the grammar — ${sheet.held} problem${sheet.held === 1 ? "" : "s"}, shown inside`}>
                            {" "}⚠
                          </span>
                        )}
                      </span>
                      <span className="refs-row-go">Open<span aria-hidden="true"> →</span></span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </div></div>
        )}

        {d && sel !== null && (
          <div className="refs-body"><div className="refs-col">
            {selExtras.length > 0 && (
              <div className="refs-extras">
                <span className="dim">also in {sel}: </span>
                {selExtras.map(e => (
                  <a key={e.file} href={obsidianHref(vault, e.file)}
                     title={`${e.file} — opens in Obsidian`}>
                    {e.title}
                  </a>
                ))}
              </div>
            )}

            {/* The dock fetches the sheet fresh on every open, exactly as the
                workbench does — a course without one shows the dock's own
                "write it with sigma guide reference" affordance. */}
            <ReferenceDock key={sel} course={sel} vault={vault} />
          </div></div>
        )}
      </div>
    </div>
  );
}
