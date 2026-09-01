/*
 * references.tsx — the rail's RF slot: every reference sheet, one door.
 *
 * The workbench already renders a course's sheet, but reaching it costs
 * opening the workbench, opening a course, and switching the dock — a route
 * you take while studying, not while checking one equation mid-problem. This
 * view is the short way in.
 *
 * **Two levels, the study room's own shape.** Opening the view lands on a
 * home — one card per course, the catalogue's visual vocabulary (`.wb-card`),
 * because choosing a sheet is the same act as choosing a course to study and
 * should look like it. Nothing is auto-opened: the last sheet you read is not
 * the sheet you came for often enough that guessing costs more than one
 * click. A card opens its course's sheet — the same `ReferenceDock` the
 * workbench mounts, same fetch, same tier toggle, so the two doors can never
 * disagree — and Esc peels sheet → home → closed, the workbench's own ladder,
 * in the capture phase so App's ladder only sees the last rung.
 *
 * Two families on purpose, mirroring GET /api/references: the contract's
 * `type: reference` sheets render here; a course's other `*-reference.md`
 * notes — imported resources that share the name but not the grammar — are
 * links into Obsidian, on the card and again above the open sheet.
 */
import { useEffect, useMemo, useState } from "react";
import { get, obsidianHref } from "./api";
import type { References, ReferenceExtraRow, ReferenceSheetRow } from "./api";
import ReferenceDock from "./reference";

function SheetCard({ course, sheet, extras, vault, onOpen }: {
  course: string;
  sheet: ReferenceSheetRow | null;
  extras: ReferenceExtraRow[];
  vault: string;
  onOpen: () => void;
}) {
  const pct = sheet
    ? Math.min(100, Math.round((sheet.exam_chars / sheet.exam_budget) * 100))
    : 0;
  return (
    <section className={`panel wb-card ${sheet && sheet.held > 0 ? "attn" : ""}`}>
      <h2>
        <button className="wb-card-open" onClick={onOpen}
                title={`open the ${course} sheet`}>{course}</button>
        <span className="wb-card-count">
          {sheet ? `${sheet.counts.all} entries` : "no sheet"}
        </span>
      </h2>

      {sheet && (
        <p className="wb-card-bar">
          <span className="cov-bar" role="img"
                aria-label={`${sheet.exam_chars} of ${sheet.exam_budget} exam-sheet characters`}>
            <span className="cov-fill" style={{ width: `${pct}%` }} />
          </span>
          <span className="dim">
            {sheet.counts.exam} on the exam sheet · {pct}% of a page
          </span>
        </p>
      )}
      {sheet && (
        <p className="wb-card-meta dim">
          {sheet.sections} section{sheet.sections === 1 ? "" : "s"}
        </p>
      )}
      {/* Held is the one thing on this screen that is genuinely on you — the
          catalogue's rule, kept: it alone gets the frame and a word. */}
      {sheet && sheet.held > 0 && (
        <p className="wb-card-meta wb-card-warn">
          ⚠ fails the grammar — {sheet.held} problem{sheet.held === 1 ? "" : "s"}, shown inside
        </p>
      )}
      {!sheet && (
        <p className="wb-card-meta dim">
          no contract sheet yet — <code>sigma guide reference {course}</code> writes one
        </p>
      )}

      {/* The imported sheets are destinations in their own right, so they are
          links here, not a count — quick access is the whole point of the
          home. Each opens in Obsidian: they share the name, not the grammar. */}
      {extras.length > 0 && (
        <ul className="refs-card-extras">
          {extras.map(e => (
            <li key={e.file}>
              <a href={obsidianHref(vault, e.file)}
                 title={`${e.file} — opens in Obsidian`}>▤ {e.title}</a>
            </li>
          ))}
        </ul>
      )}

      <p className="wb-card-act">
        <button className={`wb-btn ${sheet ? "wb-btn-primary" : ""}`} onClick={onOpen}
                title={sheet ? "open the sheet" : "open — the empty slot says how to write one"}>
          Open<span aria-hidden="true"> →</span>
        </button>
      </p>
    </section>
  );
}

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
  // the union is the card grid, so nothing with material is unreachable.
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
            <div className="wb-grid refs-grid">
              {courses.map(c => (
                <SheetCard key={c} course={c} vault={vault}
                           sheet={d.sheets.find(s => s.course === c) ?? null}
                           extras={d.extras.filter(e => e.course === c)}
                           onOpen={() => setSel(c)} />
              ))}
            </div>
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
