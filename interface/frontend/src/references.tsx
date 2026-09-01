/**
 * references.tsx — the rail's RF slot: every reference sheet, one door.
 *
 * The workbench already renders a course's sheet, but reaching it costs
 * opening the workbench, opening a course, and switching the dock — a route
 * you take while studying, not while checking one equation mid-problem. This
 * view is the short way in: every course's sheet behind one rail click, the
 * course a pill, the sheet itself the same `ReferenceDock` the workbench
 * mounts — same fetch, same tier toggle, same fill gauge, so the two doors
 * can never disagree about what the sheet says.
 *
 * Two families on purpose, mirroring GET /api/references: the contract's
 * `type: reference` sheets render here; a course's other `*-reference.md`
 * notes — imported resources that share the name but not the grammar — are
 * links into Obsidian, listed above the sheet rather than hidden, because
 * "quick access to what I look up" includes the sheets that predate the
 * grammar.
 */
import { useEffect, useMemo, useState } from "react";
import { get, obsidianHref } from "./api";
import type { References } from "./api";
import ReferenceDock from "./reference";

const COURSE_KEY = "sigma.refs.course";

export default function ReferencesView({ open, vault, onClose }: {
  open: boolean; vault: string; onClose: () => void;
}) {
  const [d, setD] = useState<References | null | undefined>(undefined);
  // Persisted like the tier toggle and for the same reason: the sheet you
  // looked up yesterday is the one you are most likely opening again.
  const [course, setCourseRaw] = useState<string | null>(() => {
    try { return localStorage.getItem(COURSE_KEY); }
    catch { return null; }
  });
  const setCourse = (c: string) => {
    setCourseRaw(c);
    try { localStorage.setItem(COURSE_KEY, c); } catch { /* private mode */ }
  };

  useEffect(() => {
    if (!open) return;
    setD(undefined);
    get<References>("references").then(setD).catch(() => setD(null));
  }, [open]);

  // Sheets first in the scan's order, then any course that only has extras —
  // the union is the pill row, so nothing with material is unreachable.
  const courses = useMemo(() => {
    if (!d) return [];
    const seen = new Set<string>();
    const out: string[] = [];
    for (const r of [...d.sheets, ...d.extras]) {
      if (!seen.has(r.course)) { seen.add(r.course); out.push(r.course); }
    }
    return out;
  }, [d]);

  // The stored course may have been archived since — fall to the first pill
  // rather than rendering a picker with nothing picked.
  const sel = course && courses.includes(course) ? course : courses[0] ?? null;
  const selExtras = d?.extras.filter(e => e.course === sel) ?? [];

  if (!open) return null;

  return (
    <div className="palette-backdrop" onClick={onClose}>
      <div className="study refs" onClick={e => e.stopPropagation()}
           role="dialog" aria-label="References">
        <header className="study-head">
          <span className="label">◇ REFERENCES — WHAT YOU LOOK UP</span>
          <button className="ghost" onClick={onClose} title="Close (Esc)">✕</button>
        </header>

        {d === undefined && <p className="dim pad">reading the sheets…</p>}
        {d === null && <p className="err pad">backend unreachable</p>}

        {d && courses.length === 0 && (
          <div className="study-body">
            <p className="dim">
              No course has a reference sheet yet. One is written from a
              course's own modules and assessments:
            </p>
            <p><code>sigma guide reference &lt;COURSE&gt;</code></p>
          </div>
        )}

        {d && courses.length > 0 && (
          <div className="study-body">
            <nav className="refs-courses" aria-label="Courses">
              {courses.map(c => {
                const sheet = d.sheets.find(s => s.course === c);
                return (
                  <button key={c} className={c === sel ? "on" : ""}
                          onClick={() => setCourse(c)}
                          title={sheet
                            ? `${sheet.counts.all} entries, ${sheet.counts.exam} on the exam sheet`
                            : "no contract sheet yet — imported material only"}>
                    {c}
                    <span className="refs-n">
                      {sheet ? sheet.counts.all : "·"}
                    </span>
                    {sheet && sheet.held > 0 && (
                      <span className="refs-held" title={`${sheet.held} grammar problem(s)`}>!</span>
                    )}
                  </button>
                );
              })}
            </nav>

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
            {sel && <ReferenceDock key={sel} course={sel} vault={vault} />}
          </div>
        )}
      </div>
    </div>
  );
}
