import { Plus, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { TaxonomyItem } from "@/api/payloads";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Field } from "@/components/ui/field";
import { Input, Textarea } from "@/components/ui/input";
import { cn } from "@/lib/cn";

/**
 * The eligibility rule editor (Behavior ELG-2).
 *
 * The rule the server stores is a tree, and a tree editor is the wrong first
 * control for the job it does: nearly every real rule is "all of these
 * conditions", where each condition is one of a small set of things a
 * coordinator actually asks for. So the default surface is a list of *clauses*
 * that compiles to `all[...]`, and anything the clause list cannot express
 * drops to raw JSON rather than being unreachable.
 *
 * `any` and `not` are built here too, one level deep, through the group
 * controls — LLD §9.1 always specified the builder as compiling presets into
 * the tree with JSON as the *advanced* fallback, and while JSON was the only
 * door a coordinator could not express a rule the engine supports (O.5).
 * Deeper nesting than one group still drops to JSON: that is a tree, and a
 * tree editor is a thing nobody has asked for.
 */

export type Rule = Record<string, unknown>;

type ClauseKind =
  | "cpi"
  | "active_backlogs"
  | "total_backlogs"
  | "tenth_percent"
  | "twelfth_percent"
  | "tenth_year"
  | "twelfth_year"
  | "study_year"
  | "graduating_year"
  | "program"
  | "component_program"
  | "secondary_program"
  | "discipline"
  | "branch"
  | "secondary_branch"
  | "minor"
  | "dual_major"
  | "dual_degree"
  | "gender"
  | "nationality"
  | "not_placed";

interface ClauseDefinition {
  kind: ClauseKind;
  label: string;
  hint: string;
}

const CLAUSES: ClauseDefinition[] = [
  { kind: "cpi", label: "Minimum CPI", hint: "Students at or above this CPI qualify." },
  {
    kind: "active_backlogs",
    label: "Maximum active backlogs",
    hint: "Usually 0 — nobody currently carrying a backlog.",
  },
  { kind: "total_backlogs", label: "Maximum total backlogs", hint: "Counts history, not just current." },
  {
    kind: "tenth_percent",
    label: "Minimum 10th percentage",
    hint: "Class X marks out of 100. A school CGPA is not converted for you.",
  },
  {
    kind: "twelfth_percent",
    label: "Minimum 12th/Diploma percentage",
    hint: "Class XII or diploma marks out of 100. A CGPA is not converted for you.",
  },
  {
    kind: "tenth_year",
    label: "10th passing years",
    hint: "One or more years, comma separated.",
  },
  {
    kind: "twelfth_year",
    label: "12th/Diploma passing years",
    hint: "One or more years, comma separated.",
  },
  {
    kind: "study_year",
    label: "Current study years",
    hint: "Years 1–8, accepted only from the configured current academic session.",
  },
  {
    kind: "graduating_year",
    label: "Graduating years",
    hint: "One or more batches, comma separated — pathways often differ, e.g. 2026, 2027.",
  },
  {
    kind: "program",
    label: "Declared programmes",
    hint: "Matches the exact programme on the student record.",
  },
  {
    kind: "component_program",
    label: "Component degrees",
    hint: "Matches a degree included in the declared programme, including combined programmes.",
  },
  {
    kind: "secondary_program",
    label: "Secondary programs",
    hint: "The postgraduate degree in a dual-degree enrollment.",
  },
  {
    kind: "discipline",
    label: "Disciplines",
    hint:
      "The disciplines this role recruits in. Matches whichever of the student's own " +
      "disciplines they may apply in — a dual major's second discipline counts from " +
      "their fourth year, and a dual degree answers with its postgraduate discipline.",
  },
  {
    kind: "branch",
    label: "Primary branch column (advanced)",
    hint:
      "Matches the primary column alone. Prefer Disciplines: naming both branch " +
      "columns excludes every single-discipline student, whose secondary is blank.",
  },
  {
    kind: "secondary_branch",
    label: "Secondary branch column (advanced)",
    hint:
      "Matches the secondary column alone, which is blank unless the student is a " +
      "dual major or dual degree. Prefer Disciplines.",
  },
  { kind: "minor", label: "Minor", hint: "Either declared minor may match." },
  {
    kind: "dual_major",
    label: "Dual majors only",
    hint: "Students completing a second major alongside their primary branch.",
  },
  {
    kind: "dual_degree",
    label: "Dual degrees only",
    hint: "Students completing a BTech–MTech or BTech–MSc dual degree.",
  },
  {
    kind: "gender",
    label: "Gender",
    hint: "Only for a drive the recruiter has scoped that way, e.g. a women-only role.",
  },
  {
    kind: "nationality",
    label: "Nationality",
    hint: "Matches the recorded nationality exactly, e.g. IN.",
  },
  {
    kind: "not_placed",
    label: "Has no accepted placement offer",
    hint: "The one context criterion — evaluated at apply time, not stored on the profile.",
  },
];

interface Clause {
  id: string;
  kind: ClauseKind;
  /** Numeric clauses. */
  number?: string;
  /** Taxonomy clauses. */
  ids?: string[];
  /** Multi-valued numeric clauses, e.g. several graduating years. */
  numbers?: string[];
  /** Fixed-choice clauses, e.g. gender. */
  choices?: string[];
  /** Free-text clauses, e.g. nationality. */
  text?: string;
}

/** The genders a profile records (`app.domain.shared.Gender`). */
const GENDERS: { value: string; label: string }[] = [
  { value: "female", label: "Female" },
  { value: "male", label: "Male" },
  { value: "other", label: "Other" },
];

/** Clause kinds whose value is a list of whole years. */
const YEAR_KINDS = new Set<ClauseKind>([
  "study_year",
  "graduating_year",
  "tenth_year",
  "twelfth_year",
]);

/** Clause kinds measured on a scale rather than counted. */
const DECIMAL_KINDS = new Set<ClauseKind>(["cpi", "tenth_percent", "twelfth_percent"]);

/**
 * One branch of a group: a set of clauses that must all hold together.
 *
 * "CSE with a CPI of 8.0" is two conditions and one option; a group of those
 * is the `any` the flat list could not express.
 */
interface Option {
  id: string;
  clauses: Clause[];
}

/**
 * `any` and `not`, compiled from controls rather than typed as JSON.
 *
 * LLD §9.1 specifies the builder as compiling presets *into* the rule tree
 * with JSON as the advanced fallback. It was the only route to nesting, which
 * made a rule the engine supports unreachable for the coordinator who wanted
 * it (observation O.5). One level of grouping covers what real rules ask for
 * — the mock run's own example is
 * `all[program in (…), any[all[branch=CSE, cpi>=8], all[branch=EE, cpi>=7.5]], backlogs=0]`
 * — and deeper nesting still drops to JSON rather than growing a general tree
 * editor nobody has asked for.
 */
interface Group {
  id: string;
  kind: "group";
  /** `any`: at least one option holds. `none`: not one of them may. */
  mode: "any" | "none";
  options: Option[];
}

type Row = Clause | Group;

function isGroup(row: Row): row is Group {
  return (row as Group).kind === "group";
}

export interface Taxonomy {
  programs: TaxonomyItem[];
  branches: TaxonomyItem[];
  minors: TaxonomyItem[];
}

function clauseProblem(clause: Clause): string | null {
  if (
    clause.kind === "dual_major" ||
    clause.kind === "dual_degree" ||
    clause.kind === "not_placed"
  ) return null;
  if (clause.kind === "gender") {
    return clause.choices?.length ? null : "Choose at least one gender.";
  }
  if (clause.kind === "nationality") {
    return clause.text?.trim() ? null : "Enter a nationality.";
  }
  if (YEAR_KINDS.has(clause.kind)) {
    const values = clause.numbers ?? [];
    const whole = values.length > 0 && values.every(
      (value) => Number.isInteger(Number(value)),
    );
    if (!whole) return "Choose at least one whole year.";
    if (
      clause.kind === "study_year" &&
      !values.every((value) => Number(value) >= 1 && Number(value) <= 8)
    ) return "Study years must be between 1 and 8.";
    // A calendar year, held to the same range the profile column accepts, so
    // a typo like 202 is refused here rather than saved as a rule nobody meets.
    if (
      clause.kind !== "study_year" &&
      !values.every((value) => Number(value) >= 1900 && Number(value) <= 2100)
    ) return "Enter a four-digit year between 1900 and 2100.";
    return null;
  }
  if (
    clause.kind === "program" ||
    clause.kind === "component_program" ||
    clause.kind === "secondary_program" ||
    clause.kind === "discipline" ||
    clause.kind === "branch" ||
    clause.kind === "secondary_branch" ||
    clause.kind === "minor"
  ) return clause.ids?.length ? null : "Choose at least one option.";
  const value = clause.number;
  if (value === undefined || value.trim() === "" || !Number.isFinite(Number(value))) {
    return "Enter a number.";
  }
  if (!DECIMAL_KINDS.has(clause.kind) && !Number.isInteger(Number(value))) {
    return "Enter a whole number.";
  }
  if (
    (clause.kind === "tenth_percent" || clause.kind === "twelfth_percent") &&
    (Number(value) < 0 || Number(value) > 100)
  ) {
    return "A percentage runs from 0 to 100.";
  }
  return null;
}

/** Why a visual draft cannot be saved; an empty top-level list is valid null. */
export function rowProblems(rows: Row[]): string[] {
  const problems: string[] = [];
  for (const row of rows) {
    if (!isGroup(row)) {
      const problem = clauseProblem(row);
      if (problem) problems.push(problem);
      continue;
    }
    if (row.options.length === 0) {
      problems.push("A group needs at least one option.");
      continue;
    }
    for (const option of row.options) {
      if (option.clauses.length === 0) {
        problems.push("Every group option needs at least one condition.");
      }
      for (const clause of option.clauses) {
        const problem = clauseProblem(clause);
        if (problem) problems.push(problem);
      }
    }
  }
  return problems;
}

/** Compile the row list to the tree the server stores. */
export function compile(rows: Row[]): Rule | null {
  return allOf(rows.map(rowToNode).filter((node): node is Rule => node !== null));
}

/** `all` of one node is that node: the schema accepts either and reads better. */
function allOf(nodes: Rule[]): Rule | null {
  if (nodes.length === 0) return null;
  if (nodes.length === 1) return nodes[0] as Rule;
  return { all: nodes };
}

function rowToNode(row: Row): Rule | null {
  if (!isGroup(row)) return toNode(row);
  const options = row.options
    .map((option) => allOf(option.clauses.map(toNode).filter((n): n is Rule => n !== null)))
    .filter((node): node is Rule => node !== null);
  if (options.length === 0) return null;
  // A one-option `any` is that option: emitting `any` of one thing would be
  // noise in the stored rule and in the summary a student reads.
  const inner = options.length === 1 ? (options[0] as Rule) : { any: options };
  return row.mode === "none" ? { not: inner } : inner;
}

function toNode(clause: Clause): Rule | null {
  switch (clause.kind) {
    case "cpi":
      return clause.number ? { field: "cpi", op: "gte", value: Number(clause.number) } : null;
    case "active_backlogs":
      return clause.number !== undefined && clause.number !== ""
        ? { field: "active_backlogs", op: "lte", value: Number(clause.number) }
        : null;
    case "total_backlogs":
      return clause.number !== undefined && clause.number !== ""
        ? { field: "total_backlogs", op: "lte", value: Number(clause.number) }
        : null;
    case "tenth_percent":
    case "twelfth_percent":
      // A floor, like CPI: the roster's school-marks criteria are all
      // "60% and above", never a band.
      return clause.number !== undefined && clause.number !== ""
        ? { field: clause.kind, op: "gte", value: Number(clause.number) }
        : null;
    case "study_year":
    case "graduating_year":
    case "tenth_year":
    case "twelfth_year": {
      const years = (clause.numbers ?? [])
        .map((entry) => Number(entry))
        .filter((year) => Number.isInteger(year));
      if (years.length === 0) return null;
      // One year stays `eq`: it keeps rules saved before this clause took a
      // list byte-identical, and "graduating year 2027" reads better than
      // "one of 2027" in the summary a student is shown.
      return years.length === 1
        ? { field: clause.kind, op: "eq", value: years[0] as number }
        : { field: clause.kind, op: "in", value: years };
    }
    case "gender": {
      const chosen = clause.choices ?? [];
      if (chosen.length === 0) return null;
      return chosen.length === 1
        ? { field: "gender", op: "eq", value: chosen[0] as string }
        : { field: "gender", op: "in", value: chosen };
    }
    case "nationality":
      return clause.text?.trim()
        ? { field: "nationality", op: "eq", value: clause.text.trim() }
        : null;
    case "program":
      return clause.ids?.length ? { field: "program_id", op: "in", value: clause.ids } : null;
    case "component_program":
      return clause.ids?.length
        ? { field: "component_program_id", op: "in", value: clause.ids }
        : null;
    case "secondary_program":
      return clause.ids?.length
        ? { field: "secondary_program_id", op: "in", value: clause.ids }
        : null;
    case "discipline":
      return clause.ids?.length
        ? { field: "discipline_id", op: "in", value: clause.ids }
        : null;
    case "branch":
      return clause.ids?.length
        ? { field: "primary_branch_id", op: "in", value: clause.ids }
        : null;
    case "secondary_branch":
      return clause.ids?.length
        ? { field: "secondary_branch_id", op: "in", value: clause.ids }
        : null;
    case "minor":
      // Either declared slot may hold it, which is a genuine `any` — the one
      // place the clause list emits something other than a flat leaf.
      return clause.ids?.length
        ? {
            any: [
              { field: "minor1_id", op: "in", value: clause.ids },
              { field: "minor2_id", op: "in", value: clause.ids },
            ],
          }
        : null;
    case "dual_major":
      return { field: "is_dual_major", op: "eq", value: true };
    case "dual_degree":
      return { field: "is_dual_degree", op: "eq", value: true };
    case "not_placed":
      return { criterion: "not_placement_placed" };
  }
}

/**
 * Read a stored tree back into clauses, so opening the editor on a saved rule
 * shows the controls rather than dropping straight to JSON.
 *
 * Returns null when the tree is not something the clause list can round-trip —
 * the editor then opens in raw mode, which is honest: a clause list that
 * silently discarded half a rule on save would be much worse than a text box.
 */
export function decompile(rule: Rule | null): Row[] | null {
  if (rule === null) return [];
  const nodes = Array.isArray(rule.all) ? (rule.all as Rule[]) : [rule];
  const rows: Row[] = [];
  for (const [index, node] of nodes.entries()) {
    const row = nodeToRow(node, String(index));
    if (row === null) return null;
    rows.push(row);
  }
  return rows;
}

function nodeToRow(node: Rule, id: string): Row | null {
  // A leaf first, because the minor clause is itself an `any` pair and must
  // not be mistaken for a group the coordinator built.
  const clause = nodeToClause(node, id);
  if (clause !== null) return clause;

  const negated = node.not !== undefined && node.not !== null;
  const inner = negated ? (node.not as Rule) : node;
  const branches = Array.isArray(inner.any)
    ? (inner.any as Rule[])
    : // `not` of a single condition is a one-option "none of these".
      negated
      ? [inner]
      : null;
  if (branches === null || branches.length === 0) return null;

  const options: Option[] = [];
  for (const [branchIndex, branch] of branches.entries()) {
    const leaves = Array.isArray(branch.all) ? (branch.all as Rule[]) : [branch];
    const clauses: Clause[] = [];
    for (const [leafIndex, leaf] of leaves.entries()) {
      const parsed = nodeToClause(leaf, `${id}-${branchIndex}-${leafIndex}`);
      // Two levels is the ceiling: a group inside a group is a tree, and a
      // tree opens in JSON rather than being flattened into a lie.
      if (parsed === null) return null;
      clauses.push(parsed);
    }
    options.push({ id: `${id}-${branchIndex}`, clauses });
  }
  return { id, kind: "group", mode: negated ? "none" : "any", options };
}

function nodeToClause(node: Rule, id: string): Clause | null {
  if (node.criterion === "not_placement_placed") return { id, kind: "not_placed" };
  if (Array.isArray(node.any)) {
    const branches = node.any as Rule[];
    const isMinorPair =
      branches.length === 2 &&
      branches[0]?.field === "minor1_id" &&
      branches[1]?.field === "minor2_id" &&
      JSON.stringify(branches[0]?.value) === JSON.stringify(branches[1]?.value);
    return isMinorPair
      ? { id, kind: "minor", ids: branches[0]?.value as string[] }
      : null;
  }
  const { field, op, value } = node as { field?: string; op?: string; value?: unknown };
  if (field === "cpi" && op === "gte") return { id, kind: "cpi", number: String(value) };
  if (field === "active_backlogs" && op === "lte")
    return { id, kind: "active_backlogs", number: String(value) };
  if (field === "total_backlogs" && op === "lte")
    return { id, kind: "total_backlogs", number: String(value) };
  if ((field === "tenth_percent" || field === "twelfth_percent") && op === "gte")
    return { id, kind: field, number: String(value) };
  if (field && YEAR_KINDS.has(field as ClauseKind)) {
    if (op === "eq") return { id, kind: field as ClauseKind, numbers: [String(value)] };
    if (op === "in")
      return { id, kind: field as ClauseKind, numbers: (value as number[]).map(String) };
  }
  if (field === "gender" && op === "eq")
    return { id, kind: "gender", choices: [String(value)] };
  if (field === "gender" && op === "in")
    return { id, kind: "gender", choices: (value as string[]).map(String) };
  if (field === "nationality" && op === "eq")
    return { id, kind: "nationality", text: String(value) };
  if (field === "program_id" && op === "in")
    return { id, kind: "program", ids: value as string[] };
  if (field === "component_program_id" && op === "in")
    return { id, kind: "component_program", ids: value as string[] };
  if (field === "secondary_program_id" && op === "in")
    return { id, kind: "secondary_program", ids: value as string[] };
  if (field === "discipline_id" && op === "in")
    return { id, kind: "discipline", ids: value as string[] };
  if (field === "primary_branch_id" && op === "in")
    return { id, kind: "branch", ids: value as string[] };
  if (field === "secondary_branch_id" && op === "in")
    return { id, kind: "secondary_branch", ids: value as string[] };
  if (field === "is_dual_major" && op === "eq" && value === true)
    return { id, kind: "dual_major" };
  if (field === "is_dual_degree" && op === "eq" && value === true)
    return { id, kind: "dual_degree" };
  return null;
}

export function RuleEditor({
  rule,
  taxonomy,
  disabled,
  outcome,
  onChange,
  onValidityChange,
}: {
  rule: Rule | null;
  taxonomy: Taxonomy;
  disabled: boolean;
  /** The job's outcome, so a clause the standing gate already enforces is not offered. */
  outcome?: string | null;
  onChange: (next: Rule | null) => void;
  onValidityChange?: (valid: boolean) => void;
}) {
  // ELG-3 already closes placement roles to a placed student before the rule
  // runs, under its own override domain. Offering the same condition here
  // invites a rule an outcome-gate override cannot lift.
  const placementOutcome = outcome === "placement";
  const initial = useMemo(() => decompile(rule), [rule]);
  const [clauses, setClauses] = useState<Row[]>(initial ?? []);
  // A tree the clause list cannot round-trip opens in raw mode rather than
  // being silently flattened.
  const [raw, setRaw] = useState(initial === null);
  const [text, setText] = useState(() => JSON.stringify(rule ?? null, null, 2));
  const [rawError, setRawError] = useState<string | undefined>(undefined);
  const visualProblems = rowProblems(clauses);

  useEffect(() => {
    onValidityChange?.(raw ? rawError === undefined : visualProblems.length === 0);
  }, [onValidityChange, raw, rawError, visualProblems.length]);

  function update(next: Row[]) {
    setClauses(next);
    if (rowProblems(next).length === 0) onChange(compile(next));
  }

  function applyRaw(value: string) {
    setText(value);
    if (!value.trim() || value.trim() === "null") {
      setRawError(undefined);
      onChange(null);
      return;
    }
    try {
      const parsed = parseRuleJson(value);
      setRawError(undefined);
      onChange(parsed);
    } catch (error) {
      setRawError(error instanceof Error ? error.message : "Not valid JSON");
    }
  }

  const compiled = raw ? null : compile(clauses);

  return (
    <div className="flex flex-col gap-gap-lg">
      <div className="flex items-center justify-between gap-gap-lg">
        <p className="text-body-sm text-muted-foreground">
          {raw
            ? "Editing the rule tree directly. Every operator the schema allows is available here."
            : "Every clause must hold. Anything this list cannot express is written as JSON."}
        </p>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            if (!raw) {
              setText(JSON.stringify(compiled, null, 2));
              setRaw(true);
              return;
            }
            try {
              const recovered = decompile(parseRuleJson(text));
              if (recovered === null) {
                setRawError("This tree cannot be represented by the visual clauses.");
                return;
              }
              setClauses(recovered);
              setRawError(undefined);
              setRaw(false);
            } catch (error) {
              setRawError(error instanceof Error ? error.message : "Not valid JSON");
            }
          }}
        >
          {raw ? "Back to clauses" : "Edit as JSON"}
        </Button>
      </div>

      {raw ? (
        <Field
          label="Rule tree"
          {...(rawError ? { error: rawError } : {})}
          hint="null means no rule: open to every active member of the cycle."
        >
          {(field) => (
            <Textarea
              {...field}
              disabled={disabled}
              className="min-h-[240px] font-medium"
              value={text}
              onChange={(event) => applyRaw(event.target.value)}
            />
          )}
        </Field>
      ) : (
        <>
          {visualProblems.length > 0 ? (
            <p role="alert" className="text-body-sm text-destructive">
              Complete or remove every unfinished condition before saving.
            </p>
          ) : null}
          {clauses.length === 0 ? (
            <p className="rounded border border-border bg-muted p-gap-lg text-body-md text-muted-foreground">
              No clauses. The job is open to every active member of the cycle.
            </p>
          ) : (
            <ul className="flex flex-col gap-gap-lg">
              {clauses.map((row, index) => (
                <li key={row.id}>
                  {isGroup(row) ? (
                    <GroupRow
                      group={row}
                      taxonomy={taxonomy}
                      disabled={disabled}
                      placementOutcome={placementOutcome}
                      onChange={(next) =>
                        update(clauses.map((item, i) => (i === index ? next : item)))
                      }
                      onRemove={() => update(clauses.filter((_, i) => i !== index))}
                    />
                  ) : (
                    <ClauseRow
                      clause={row}
                      taxonomy={taxonomy}
                      disabled={disabled}
                      placementOutcome={placementOutcome}
                      onChange={(next) =>
                        update(clauses.map((item, i) => (i === index ? next : item)))
                      }
                      onRemove={() => update(clauses.filter((_, i) => i !== index))}
                    />
                  )}
                </li>
              ))}
            </ul>
          )}

          {/* Named, because every option carries the same palette: without a
              name, "add a CPI clause" means one of several identical buttons. */}
          <div
            role="group"
            aria-label="Add a condition or a group"
            className="flex flex-wrap gap-gap-md"
          >
            <AddClauseButtons
              disabled={disabled}
              placementOutcome={placementOutcome}
              onAdd={(kind) =>
                update([...clauses, { id: `${kind}-${Date.now()}`, kind }])
              }
            />
            {/* The two group shapes, which the flat list could not express and
                which LLD §9.1 always intended the builder to compile. */}
            <Button
              variant="secondary"
              size="sm"
              disabled={disabled}
              icon={<Plus className="h-4 w-4" />}
              onClick={() => update([...clauses, newGroup("any")])}
            >
              Any of these
            </Button>
            <Button
              variant="secondary"
              size="sm"
              disabled={disabled}
              icon={<Plus className="h-4 w-4" />}
              onClick={() => update([...clauses, newGroup("none")])}
            >
              None of these
            </Button>
          </div>
        </>
      )}
    </div>
  );
}

export function parseRuleJson(text: string): Rule | null {
  assertNoDuplicateJsonKeys(text);
  const parsed = JSON.parse(text) as unknown;
  if (parsed === null) return null;
  if (typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("A rule must be a JSON object or null.");
  }
  return parsed as Rule;
}

/** Detect object-key duplication before JSON.parse discards the earlier value. */
function assertNoDuplicateJsonKeys(text: string): void {
  let index = 0;
  const whitespace = () => {
    while (/\s/.test(text[index] ?? "")) index += 1;
  };
  const stringToken = (): string => {
    const start = index;
    index += 1;
    while (index < text.length) {
      if (text[index] === "\\") {
        index += 2;
      } else if (text[index] === '"') {
        index += 1;
        return JSON.parse(text.slice(start, index)) as string;
      } else {
        index += 1;
      }
    }
    throw new SyntaxError("Unterminated JSON string");
  };
  const value = (): void => {
    whitespace();
    if (text[index] === "{") {
      index += 1;
      whitespace();
      const keys = new Set<string>();
      if (text[index] === "}") { index += 1; return; }
      while (index < text.length) {
        if (text[index] !== '"') throw new SyntaxError("Expected a JSON object key");
        const key = stringToken();
        if (keys.has(key)) throw new SyntaxError(`Duplicate JSON key: ${key}`);
        keys.add(key);
        whitespace();
        if (text[index] !== ":") throw new SyntaxError("Expected ':' after JSON key");
        index += 1;
        value();
        whitespace();
        if (text[index] === "}") { index += 1; return; }
        if (text[index] !== ",") throw new SyntaxError("Expected ',' in JSON object");
        index += 1;
        whitespace();
      }
      throw new SyntaxError("Unterminated JSON object");
    }
    if (text[index] === "[") {
      index += 1;
      whitespace();
      if (text[index] === "]") { index += 1; return; }
      while (index < text.length) {
        value();
        whitespace();
        if (text[index] === "]") { index += 1; return; }
        if (text[index] !== ",") throw new SyntaxError("Expected ',' in JSON array");
        index += 1;
      }
      throw new SyntaxError("Unterminated JSON array");
    }
    if (text[index] === '"') { stringToken(); return; }
    const match = /^(?:true|false|null|-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?)/
      .exec(text.slice(index));
    if (!match) throw new SyntaxError("Invalid JSON value");
    index += match[0].length;
  };
  value();
  whitespace();
  if (index !== text.length) throw new SyntaxError("Unexpected text after JSON value");
}

function newGroup(mode: "any" | "none"): Group {
  const stamp = Date.now();
  return {
    id: `group-${stamp}`,
    kind: "group",
    mode,
    // Two options, because one is not an alternative to anything and a group
    // that starts empty does not say what it is for.
    options: [
      { id: `option-${stamp}-0`, clauses: [] },
      { id: `option-${stamp}-1`, clauses: [] },
    ],
  };
}

/** The clause palette; predicates may repeat wherever the rule needs them. */
function AddClauseButtons({
  disabled,
  placementOutcome,
  onAdd,
}: {
  disabled: boolean;
  placementOutcome: boolean;
  onAdd: (kind: ClauseKind) => void;
}) {
  return (
    <>
      {CLAUSES.filter(
        (definition) => !(definition.kind === "not_placed" && placementOutcome),
      ).map((definition) => (
        <Button
          key={definition.kind}
          variant="secondary"
          size="sm"
          disabled={disabled}
          icon={<Plus className="h-4 w-4" />}
          onClick={() => onAdd(definition.kind)}
        >
          {definition.label}
        </Button>
      ))}
    </>
  );
}

function GroupRow({
  group,
  taxonomy,
  disabled,
  placementOutcome,
  onChange,
  onRemove,
}: {
  group: Group;
  taxonomy: Taxonomy;
  disabled: boolean;
  placementOutcome: boolean;
  onChange: (next: Group) => void;
  onRemove: () => void;
}) {
  const label = group.mode === "any" ? "Any of these" : "None of these";
  const hint =
    group.mode === "any"
      ? "At least one option must hold. Each option is every condition inside it, together."
      : "No option may hold. Each option is every condition inside it, together.";

  function setOptions(options: Option[]) {
    onChange({ ...group, options });
  }

  const labelId = `group-${group.id}-label`;
  return (
    <div
      role="region"
      aria-labelledby={labelId}
      className="rounded border border-border bg-card p-gap-lg"
    >
      <div className="flex items-start justify-between gap-gap-lg">
        <div className="min-w-0 flex-1">
          <p id={labelId} className="text-body-md font-semibold text-foreground">
            {label}
          </p>
          <p className="text-body-sm text-muted-foreground">{hint}</p>
        </div>
        <Button
          variant="destructive-ghost"
          size="icon-sm"
          aria-label={`Remove ${label}`}
          disabled={disabled}
          onClick={onRemove}
        >
          <Trash2 className="h-4 w-4" />
        </Button>
      </div>

      <ul className="mt-gap-lg flex flex-col gap-gap-lg">
        {group.options.map((option, optionIndex) => (
          <li
            key={option.id}
            // Named as a group: one option holds several conditions, and
            // addressing it by name is what keeps "the branch in option 2"
            // from meaning "the second checkbox on screen".
            role="group"
            aria-labelledby={`${option.id}-label`}
            className="rounded border border-border bg-muted p-gap-lg"
          >
            <div className="flex items-center justify-between gap-gap-lg">
              <p
                id={`${option.id}-label`}
                className="text-label-caps uppercase text-muted-foreground"
              >
                Option {optionIndex + 1}
              </p>
              {group.options.length > 1 ? (
                <Button
                  variant="destructive-ghost"
                  size="icon-sm"
                  aria-label={`Remove option ${optionIndex + 1}`}
                  disabled={disabled}
                  onClick={() =>
                    setOptions(group.options.filter((_, i) => i !== optionIndex))
                  }
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              ) : null}
            </div>

            {option.clauses.length === 0 ? (
              <p className="mt-gap-md text-body-sm text-muted-foreground">
                No conditions yet. An empty option is ignored.
              </p>
            ) : (
              <ul className="mt-gap-md flex flex-col gap-gap-md">
                {option.clauses.map((clause, clauseIndex) => (
                  <li key={clause.id}>
                    <ClauseRow
                      clause={clause}
                      taxonomy={taxonomy}
                      disabled={disabled}
                      placementOutcome={placementOutcome}
                      onChange={(next) =>
                        setOptions(
                          group.options.map((item, i) =>
                            i === optionIndex
                              ? {
                                  ...item,
                                  clauses: item.clauses.map((existing, j) =>
                                    j === clauseIndex ? next : existing,
                                  ),
                                }
                              : item,
                          ),
                        )
                      }
                      onRemove={() =>
                        setOptions(
                          group.options.map((item, i) =>
                            i === optionIndex
                              ? {
                                  ...item,
                                  clauses: item.clauses.filter((_, j) => j !== clauseIndex),
                                }
                              : item,
                          ),
                        )
                      }
                    />
                  </li>
                ))}
              </ul>
            )}

            <div
              role="group"
              aria-label={`Add a condition to option ${optionIndex + 1}`}
              className="mt-gap-md flex flex-wrap gap-gap-md"
            >
              <AddClauseButtons
                disabled={disabled}
                placementOutcome={placementOutcome}
                onAdd={(kind) =>
                  setOptions(
                    group.options.map((item, i) =>
                      i === optionIndex
                        ? {
                            ...item,
                            clauses: [
                              ...item.clauses,
                              { id: `${kind}-${optionIndex}-${Date.now()}`, kind },
                            ],
                          }
                        : item,
                    ),
                  )
                }
              />
            </div>
          </li>
        ))}
      </ul>

      <Button
        className="mt-gap-lg"
        variant="secondary"
        size="sm"
        disabled={disabled}
        icon={<Plus className="h-4 w-4" />}
        onClick={() =>
          setOptions([
            ...group.options,
            { id: `option-${group.id}-${Date.now()}`, clauses: [] },
          ])
        }
      >
        Add option
      </Button>
    </div>
  );
}

function ClauseRow({
  clause,
  taxonomy,
  disabled,
  placementOutcome,
  onChange,
  onRemove,
}: {
  clause: Clause;
  taxonomy: Taxonomy;
  disabled: boolean;
  placementOutcome: boolean;
  onChange: (next: Clause) => void;
  onRemove: () => void;
}) {
  const definition = CLAUSES.find((entry) => entry.kind === clause.kind);
  const options =
    clause.kind === "program" ||
    clause.kind === "component_program" ||
    clause.kind === "secondary_program"
      ? taxonomy.programs
      : clause.kind === "discipline" ||
          clause.kind === "branch" ||
          clause.kind === "secondary_branch"
        ? taxonomy.branches
        : clause.kind === "minor"
          ? taxonomy.minors
          : null;

  // Named as a region: a clause is an editable group of controls, and naming
  // it by its own label is what lets one clause be addressed out of several
  // — including the same clause kind inside two different group options.
  const labelId = `clause-${clause.id}-label`;
  return (
    <div
      role="region"
      aria-labelledby={labelId}
      className="rounded border border-border bg-card p-gap-lg"
    >
      <div className="flex items-start justify-between gap-gap-lg">
        <div className="min-w-0 flex-1">
          <p id={labelId} className="text-body-md font-semibold text-foreground">
            {definition?.label}
          </p>
          <p className="text-body-sm text-muted-foreground">{definition?.hint}</p>
        </div>
        <Button
          variant="destructive-ghost"
          size="icon-sm"
          aria-label={`Remove ${definition?.label}`}
          disabled={disabled}
          onClick={onRemove}
        >
          <Trash2 className="h-4 w-4" />
        </Button>
      </div>

      <div className="mt-gap-lg">
        {options ? (
          <div className="flex flex-wrap gap-gap-lg">
            {options.map((item) => (
              <label
                key={item.id}
                className={cn(
                  "flex items-center gap-gap-md text-body-md",
                  item.is_active ? "text-foreground" : "text-muted-foreground",
                )}
              >
                <Checkbox
                  disabled={disabled}
                  checked={clause.ids?.includes(item.id) ?? false}
                  onChange={(event) =>
                    onChange({
                      ...clause,
                      ids: event.target.checked
                        ? [...(clause.ids ?? []), item.id]
                        : (clause.ids ?? []).filter((id) => id !== item.id),
                    })
                  }
                />
                {item.name}
                {item.is_active ? null : " (inactive)"}
              </label>
            ))}
          </div>
        ) : clause.kind === "gender" ? (
          <div className="flex flex-wrap gap-gap-lg">
            {GENDERS.map((item) => (
              <label key={item.value} className="flex items-center gap-gap-md text-body-md">
                <Checkbox
                  disabled={disabled}
                  checked={clause.choices?.includes(item.value) ?? false}
                  onChange={(event) =>
                    onChange({
                      ...clause,
                      choices: event.target.checked
                        ? [...(clause.choices ?? []), item.value]
                        : (clause.choices ?? []).filter((value) => value !== item.value),
                    })
                  }
                />
                {item.label}
              </label>
            ))}
          </div>
        ) : clause.kind === "nationality" ? (
          <Input
            aria-label={definition?.label}
            type="text"
            placeholder="IN"
            className="w-64"
            disabled={disabled}
            value={clause.text ?? ""}
            onChange={(event) => onChange({ ...clause, text: event.target.value })}
          />
        ) : YEAR_KINDS.has(clause.kind) ? (
          <Input
            aria-label={definition?.label}
            type="text"
            inputMode="numeric"
            placeholder={clause.kind === "study_year" ? "3, 4" : "2026, 2027"}
            className="w-64"
            disabled={disabled}
            value={(clause.numbers ?? []).join(", ")}
            onChange={(event) =>
              onChange({
                ...clause,
                numbers: event.target.value
                  .split(",")
                  .map((entry) => entry.trim())
                  .filter((entry) => entry !== ""),
              })
            }
          />
        ) : clause.kind === "dual_major" || clause.kind === "dual_degree" || clause.kind === "not_placed" ? (
          <p className="text-body-sm text-muted-foreground">
            {clause.kind === "not_placed" && placementOutcome
              ? "Already enforced for placement roles before a student can apply, so this clause changes nothing. Remove it — an override of the standing gate cannot lift a rule."
              : "This clause takes no value — adding it is the whole condition."}
          </p>
        ) : (
          <Input
            aria-label={definition?.label ?? "Value"}
            type="number"
            step={DECIMAL_KINDS.has(clause.kind) ? "0.01" : "1"}
            className="w-40"
            disabled={disabled}
            value={clause.number ?? ""}
            onChange={(event) => onChange({ ...clause, number: event.target.value })}
          />
        )}
      </div>
    </div>
  );
}

export type { Clause, Group, Option, Row };
