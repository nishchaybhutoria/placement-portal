import { Plus, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";

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
  | "graduating_year"
  | "program"
  | "secondary_program"
  | "branch"
  | "secondary_branch"
  | "minor"
  | "dual_major"
  | "dual_degree"
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
  { kind: "graduating_year", label: "Graduating year", hint: "Exactly this batch." },
  { kind: "program", label: "Primary programs", hint: "Any primary degree you pick." },
  {
    kind: "secondary_program",
    label: "Secondary programs",
    hint: "The postgraduate degree in a dual-degree enrollment.",
  },
  { kind: "branch", label: "Primary branches", hint: "Any primary discipline you pick." },
  {
    kind: "secondary_branch",
    label: "Secondary branches",
    hint: "The second major or postgraduate discipline.",
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
}

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
    case "graduating_year":
      return clause.number
        ? { field: "graduating_year", op: "eq", value: Number(clause.number) }
        : null;
    case "program":
      return clause.ids?.length ? { field: "program_id", op: "in", value: clause.ids } : null;
    case "secondary_program":
      return clause.ids?.length
        ? { field: "secondary_program_id", op: "in", value: clause.ids }
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
  if (field === "graduating_year" && op === "eq")
    return { id, kind: "graduating_year", number: String(value) };
  if (field === "program_id" && op === "in")
    return { id, kind: "program", ids: value as string[] };
  if (field === "secondary_program_id" && op === "in")
    return { id, kind: "secondary_program", ids: value as string[] };
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
  onChange,
}: {
  rule: Rule | null;
  taxonomy: Taxonomy;
  disabled: boolean;
  onChange: (next: Rule | null) => void;
}) {
  const initial = useMemo(() => decompile(rule), [rule]);
  const [clauses, setClauses] = useState<Row[]>(initial ?? []);
  // A tree the clause list cannot round-trip opens in raw mode rather than
  // being silently flattened.
  const [raw, setRaw] = useState(initial === null);
  const [text, setText] = useState(() => JSON.stringify(rule ?? null, null, 2));
  const [rawError, setRawError] = useState<string | undefined>(undefined);

  function update(next: Row[]) {
    setClauses(next);
    onChange(compile(next));
  }

  function applyRaw(value: string) {
    setText(value);
    if (!value.trim() || value.trim() === "null") {
      setRawError(undefined);
      onChange(null);
      return;
    }
    try {
      const parsed = JSON.parse(value) as Rule;
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
            if (!raw) setText(JSON.stringify(compiled, null, 2));
            else {
              const recovered = decompile(safeParse(text));
              if (recovered) setClauses(recovered);
            }
            setRaw((open) => !open);
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
              taken={clauses.filter((row): row is Clause => !isGroup(row))}
              disabled={disabled}
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

function safeParse(text: string): Rule | null {
  try {
    return JSON.parse(text) as Rule;
  } catch {
    return null;
  }
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

/**
 * The clause palette, filtered by what is already present *at this level*.
 *
 * Filtering globally would be wrong now that groups exist: "branch is CSE" in
 * one option and "branch is EE" in another is the whole point of a group, and
 * a palette that hid the second one would make the rule unbuildable again.
 */
function AddClauseButtons({
  taken,
  disabled,
  onAdd,
}: {
  taken: Clause[];
  disabled: boolean;
  onAdd: (kind: ClauseKind) => void;
}) {
  return (
    <>
      {CLAUSES.filter(
        (definition) => !taken.some((clause) => clause.kind === definition.kind),
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
  onChange,
  onRemove,
}: {
  group: Group;
  taxonomy: Taxonomy;
  disabled: boolean;
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
                taken={option.clauses}
                disabled={disabled}
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
  onChange,
  onRemove,
}: {
  clause: Clause;
  taxonomy: Taxonomy;
  disabled: boolean;
  onChange: (next: Clause) => void;
  onRemove: () => void;
}) {
  const definition = CLAUSES.find((entry) => entry.kind === clause.kind);
  const options =
    clause.kind === "program" || clause.kind === "secondary_program"
      ? taxonomy.programs
      : clause.kind === "branch" || clause.kind === "secondary_branch"
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
        ) : clause.kind === "dual_major" || clause.kind === "dual_degree" || clause.kind === "not_placed" ? (
          <p className="text-body-sm text-muted-foreground">
            This clause takes no value — adding it is the whole condition.
          </p>
        ) : (
          <Input
            aria-label={definition?.label ?? "Value"}
            type="number"
            step={clause.kind === "cpi" ? "0.01" : "1"}
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
