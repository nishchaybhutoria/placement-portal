import { describe, expect, it } from "vitest";

import { compile, decompile, type Row } from "./RuleEditor";

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

  it("ignores an option with nothing in it, and a group with no options", () => {
    expect(
      compile([
        {
          id: "1",
          kind: "group",
          mode: "any",
          options: [
            { id: "1-0", clauses: [{ id: "a", kind: "dual_major" }] },
            { id: "1-1", clauses: [] },
          ],
        },
      ]),
    ).toEqual({ field: "is_dual_major", op: "eq", value: true });
    expect(
      compile([{ id: "1", kind: "group", mode: "any", options: [{ id: "x", clauses: [] }] }]),
    ).toBeNull();
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
});
