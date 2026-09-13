import { describe, expect, it } from "vitest";

import {
  compile,
  decompile,
  parseRuleJson,
  rowProblems,
  type Row,
} from "./RuleEditor";

/**
 * The compile/decompile pair, which is the whole contract of the editor.
 *
 * A clause list that cannot read back what it wrote is worse than a text box:
 * it opens on a saved rule, shows something else, and saves *that*. So the
 * property asserted throughout is round-tripping — build, compile, decompile,
 * compile again, and land on the identical tree.
 *
 * The rule that motivated the group controls is Step 19's, which the mock run
 * hands to a student to build unaided (observation O.5, ruled a product gap):
 *
 *   program in (BTech, Dual Major)
 *   AND ((branch = CSE AND CPI >= 8.0) OR (branch = EE AND CPI >= 7.5))
 *   AND active backlogs = 0
 */

const BTECH = "11111111-1111-4111-8111-111111111111";
const DUAL = "22222222-2222-4222-8222-222222222222";
const CSE = "33333333-3333-4333-8333-333333333333";
const EE = "44444444-4444-4444-8444-444444444444";
const ME = "55555555-5555-4555-8555-555555555555";
const MINOR_CSE = "66666666-6666-4666-8666-666666666666";

function roundTrip(rows: Row[]) {
  const compiled = compile(rows);
  const recovered = decompile(compiled);
  expect(recovered, "the editor cannot read back what it just wrote").not.toBeNull();
  expect(compile(recovered ?? [])).toEqual(compiled);
  return compiled;
}

describe("rule compilation", () => {
  it("compiles Step 19's rule, which needed JSON before the group controls", () => {
    const rows: Row[] = [
      { id: "1", kind: "program", ids: [BTECH, DUAL] },
      {
        id: "2",
        kind: "group",
        mode: "any",
        options: [
          {
            id: "2-0",
            clauses: [
              { id: "2-0-0", kind: "branch", ids: [CSE] },
              { id: "2-0-1", kind: "cpi", number: "8.0" },
            ],
          },
          {
            id: "2-1",
            clauses: [
              { id: "2-1-0", kind: "branch", ids: [EE] },
              { id: "2-1-1", kind: "cpi", number: "7.5" },
            ],
          },
        ],
      },
      { id: "3", kind: "active_backlogs", number: "0" },
    ];

    expect(roundTrip(rows)).toEqual({
      all: [
        { field: "program_id", op: "in", value: [BTECH, DUAL] },
        {
          any: [
            {
              all: [
                { field: "primary_branch_id", op: "in", value: [CSE] },
                { field: "cpi", op: "gte", value: 8 },
              ],
            },
            {
              all: [
                { field: "primary_branch_id", op: "in", value: [EE] },
                { field: "cpi", op: "gte", value: 7.5 },
              ],
            },
          ],
        },
        { field: "active_backlogs", op: "lte", value: 0 },
      ],
    });
  });

  it("negates a group as `not`, and round-trips it", () => {
    const compiled = roundTrip([
      {
        id: "1",
        kind: "group",
        mode: "none",
        options: [
          { id: "1-0", clauses: [{ id: "a", kind: "branch", ids: [CSE] }] },
          { id: "1-1", clauses: [{ id: "b", kind: "dual_degree" }] },
        ],
      },
    ]);
    expect(compiled).toEqual({
      not: {
        any: [
          { field: "primary_branch_id", op: "in", value: [CSE] },
          { field: "is_dual_degree", op: "eq", value: true },
        ],
      },
    });
  });

  it("does not wrap a one-option group in `any`", () => {
    // `any` of one thing is that thing. Emitting the wrapper would be noise in
    // the stored rule and in the ELG-2 summary a refused student reads.
    expect(
      compile([
        {
          id: "1",
          kind: "group",
          mode: "any",
          options: [{ id: "1-0", clauses: [{ id: "a", kind: "dual_major" }] }],
        },
      ]),
    ).toEqual({ field: "is_dual_major", op: "eq", value: true });
  });

  it("marks empty options invalid instead of silently saving around them", () => {
    const unfinished: Row[] = [
      {
        id: "1",
        kind: "group",
        mode: "any",
        options: [
          { id: "1-0", clauses: [{ id: "a", kind: "dual_major" }] },
          { id: "1-1", clauses: [] },
        ],
      },
    ];
    expect(rowProblems(unfinished)).toEqual([
      "Every group option needs at least one condition.",
    ]);
    expect(
      rowProblems([
        { id: "cpi", kind: "cpi" },
        { id: "program", kind: "program", ids: [] },
      ]),
    ).toHaveLength(2);
  });

  it("keeps the minor pair a clause, not a group the coordinator built", () => {
    // The minor clause compiles to its own `any` over two profile slots. It
    // has to decompile back to one clause: reading it as a group would show a
    // coordinator two options they never created, and offering to edit them
    // would let them write a rule the picker cannot express.
    const compiled = roundTrip([{ id: "1", kind: "minor", ids: [CSE] }]);
    expect(compiled).toEqual({
      any: [
        { field: "minor1_id", op: "in", value: [CSE] },
        { field: "minor2_id", op: "in", value: [CSE] },
      ],
    });
    const recovered = decompile(compiled);
    expect(recovered).toHaveLength(1);
    expect(recovered?.[0]).toMatchObject({ kind: "minor", ids: [CSE] });
  });

  it("refuses a tree deeper than one group, so it opens in JSON instead", () => {
    // Silently flattening this would save a different rule than the one on
    // screen. Returning null is what makes the editor open in raw mode.
    expect(
      decompile({
        all: [{ any: [{ any: [{ field: "cpi", op: "gte", value: 8 }] }] }],
      }),
    ).toBeNull();
    expect(decompile({ field: "cpi", op: "unsupported_op", value: 8 })).toBeNull();
  });

  it("reads a stored `any` of bare leaves as a group of single-condition options", () => {
    const rows = decompile({
      any: [
        { field: "primary_branch_id", op: "in", value: [CSE] },
        { field: "primary_branch_id", op: "in", value: [EE] },
      ],
    });
    expect(rows).toHaveLength(1);
    expect(rows?.[0]).toMatchObject({ kind: "group", mode: "any" });
  });

  it("still compiles a flat list to `all`, and one clause to itself", () => {
    expect(
      compile([
        { id: "1", kind: "cpi", number: "7" },
        { id: "2", kind: "not_placed" },
      ]),
    ).toEqual({
      all: [
        { field: "cpi", op: "gte", value: 7 },
        { criterion: "not_placement_placed" },
      ],
    });
    expect(compile([{ id: "1", kind: "not_placed" }])).toEqual({
      criterion: "not_placement_placed",
    });
    expect(compile([])).toBeNull();
    expect(decompile(null)).toEqual([]);
  });

  it("keeps declared programmes separate from component degrees", () => {
    expect(
      compile([
        { id: "declared", kind: "program", ids: [BTECH] },
        { id: "component", kind: "component_program", ids: [DUAL] },
      ]),
    ).toEqual({
      all: [
        { field: "program_id", op: "in", value: [BTECH] },
        { field: "component_program_id", op: "in", value: [DUAL] },
      ],
    });
    roundTrip([{ id: "component", kind: "component_program", ids: [BTECH] }]);
  });

  it("states a discipline condition once instead of naming both branch columns", () => {
    // The defect this clause exists for: ANDing the two columns excluded every
    // single-discipline student, whose secondary branch is blank.
    expect(compile([{ id: "1", kind: "discipline", ids: [CSE, EE] }])).toEqual({
      field: "discipline_id",
      op: "in",
      value: [CSE, EE],
    });
    roundTrip([{ id: "1", kind: "discipline", ids: [CSE, EE] }]);
  });

  it("compiles current study years as an explicit session-qualified field", () => {
    expect(compile([{ id: "1", kind: "study_year", numbers: ["3", "4"] }])).toEqual({
      field: "study_year",
      op: "in",
      value: [3, 4],
    });
    expect(rowProblems([{ id: "1", kind: "study_year", numbers: ["9"] }])).toEqual([
      "Study years must be between 1 and 8.",
    ]);
    roundTrip([{ id: "1", kind: "study_year", numbers: ["3", "4"] }]);
  });

  it("carries several graduating years, and keeps a single year as `eq`", () => {
    // Pathways differ: the roster gives dual degrees their own graduating year.
    expect(compile([{ id: "1", kind: "graduating_year", numbers: ["2026", "2027"] }])).toEqual({
      field: "graduating_year",
      op: "in",
      value: [2026, 2027],
    });
    expect(compile([{ id: "1", kind: "graduating_year", numbers: ["2027"] }])).toEqual({
      field: "graduating_year",
      op: "eq",
      value: 2027,
    });
    expect(compile([{ id: "1", kind: "graduating_year", numbers: [] }])).toBeNull();
    roundTrip([{ id: "1", kind: "graduating_year", numbers: ["2026", "2027"] }]);
    // A rule saved before the clause took a list still opens in the controls.
    expect(decompile({ field: "graduating_year", op: "eq", value: 2027 })).toEqual([
      { id: "0", kind: "graduating_year", numbers: ["2027"] },
    ]);
  });

  it("rejects duplicate JSON keys before JSON.parse can discard one", () => {
    expect(() =>
      parseRuleJson('{"field":"cpi","op":"gte","value":8,"value":9}'),
    ).toThrow(/Duplicate JSON key: value/);
    expect(parseRuleJson('{"field":"cpi","op":"gte","value":8}')).toEqual({
      field: "cpi",
      op: "gte",
      value: 8,
    });
    expect(parseRuleJson("null")).toBeNull();
    expect(() => parseRuleJson("[]")).toThrow(/JSON object or null/);
  });

  it("round-trips a per-pathway rule of the shape the roster describes", () => {
    // "BTech graduating 2027 in CSE, or a dual degree graduating 2026 in EE."
    roundTrip([
      {
        id: "1",
        kind: "group",
        mode: "any",
        options: [
          {
            id: "1-0",
            clauses: [
              { id: "1-0-0", kind: "program", ids: [BTECH] },
              { id: "1-0-1", kind: "discipline", ids: [CSE] },
              { id: "1-0-2", kind: "graduating_year", numbers: ["2027"] },
            ],
          },
          {
            id: "1-1",
            clauses: [
              { id: "1-1-0", kind: "program", ids: [DUAL] },
              { id: "1-1-1", kind: "discipline", ids: [EE] },
              { id: "1-1-2", kind: "graduating_year", numbers: ["2026"] },
            ],
          },
        ],
      },
    ]);
  });

  it("compiles the identity and school-marks clauses the roster's criteria ask for", () => {
    // The criteria column asks for these in plain words -- "female students
    // graduating in 2027", "minimum 60% marks in 10th and 12th" -- and until
    // they had controls they were reachable only by hand-writing JSON.
    expect(
      compile([
        { id: "1", kind: "gender", choices: ["female"] },
        { id: "2", kind: "tenth_percent", number: "60" },
        { id: "3", kind: "twelfth_percent", number: "60" },
      ]),
    ).toEqual({
      all: [
        { field: "gender", op: "eq", value: "female" },
        { field: "tenth_percent", op: "gte", value: 60 },
        { field: "twelfth_percent", op: "gte", value: 60 },
      ],
    });
    // Several genders are a list, exactly as several years are.
    expect(compile([{ id: "1", kind: "gender", choices: ["female", "other"] }])).toEqual({
      field: "gender",
      op: "in",
      value: ["female", "other"],
    });
    expect(compile([{ id: "1", kind: "nationality", text: " IN " }])).toEqual({
      field: "nationality",
      op: "eq",
      value: "IN",
    });
    roundTrip([
      { id: "1", kind: "gender", choices: ["female", "other"] },
      { id: "2", kind: "nationality", text: "IN" },
      { id: "3", kind: "tenth_percent", number: "70.5" },
      { id: "4", kind: "twelfth_year", numbers: ["2021", "2022"] },
      { id: "5", kind: "tenth_year", numbers: ["2019"] },
    ]);
  });

  it("holds school marks and calendar years to the profile column's own range", () => {
    expect(rowProblems([{ id: "1", kind: "tenth_percent", number: "120" }])).toEqual([
      "A percentage runs from 0 to 100.",
    ]);
    expect(rowProblems([{ id: "1", kind: "twelfth_year", numbers: ["202"] }])).toEqual([
      "Enter a four-digit year between 1900 and 2100.",
    ]);
    expect(rowProblems([{ id: "1", kind: "gender", choices: [] }])).toEqual([
      "Choose at least one gender.",
    ]);
    expect(rowProblems([{ id: "1", kind: "nationality", text: "  " }])).toEqual([
      "Enter a nationality.",
    ]);
    // A percentage is measured, not counted: 70.5 is a legitimate 12th mark.
    expect(rowProblems([{ id: "1", kind: "twelfth_percent", number: "70.5" }])).toEqual([]);
  });

  it("expresses the roster's conditional-minor pathway without nesting a group", () => {
    // The roster opens several pathways to a branch only "if pursuing Minor in
    // CSE/AI". Written as one discipline list plus a conditional, that is a
    // group inside a group option -- JSON only. Written as the two pathways it
    // really is, it is two options of one `any`, which the controls express.
    const compiled = roundTrip([
      { id: "cpi", kind: "cpi", number: "7" },
      { id: "backlogs", kind: "active_backlogs", number: "0" },
      {
        id: "pathways",
        kind: "group",
        mode: "any",
        options: [
          {
            id: "p0",
            clauses: [
              { id: "p0-0", kind: "discipline", ids: [CSE, EE] },
              { id: "p0-1", kind: "study_year", numbers: ["3", "4"] },
              { id: "p0-2", kind: "graduating_year", numbers: ["2027"] },
            ],
          },
          {
            id: "p1",
            clauses: [
              { id: "p1-0", kind: "discipline", ids: [ME] },
              { id: "p1-1", kind: "minor", ids: [MINOR_CSE] },
              { id: "p1-2", kind: "study_year", numbers: ["3", "4"] },
              { id: "p1-3", kind: "graduating_year", numbers: ["2027"] },
            ],
          },
        ],
      },
    ]);
    // The minor clause is itself an `any` pair, and it sits inside a group
    // option here -- the one place a clause could be mistaken for nesting.
    const years = [
      { field: "study_year", op: "in", value: [3, 4] },
      { field: "graduating_year", op: "eq", value: 2027 },
    ];
    expect(compiled).toEqual({
      all: [
        { field: "cpi", op: "gte", value: 7 },
        { field: "active_backlogs", op: "lte", value: 0 },
        {
          any: [
            {
              all: [{ field: "discipline_id", op: "in", value: [CSE, EE] }, ...years],
            },
            {
              all: [
                { field: "discipline_id", op: "in", value: [ME] },
                {
                  any: [
                    { field: "minor1_id", op: "in", value: [MINOR_CSE] },
                    { field: "minor2_id", op: "in", value: [MINOR_CSE] },
                  ],
                },
                ...years,
              ],
            },
          ],
        },
      ],
    });
  });
});
