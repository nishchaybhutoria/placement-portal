import { Plus } from "lucide-react";
import { useState, type ChangeEvent } from "react";

import { payload, type TaxonomiesPayload, type TaxonomyItem } from "@/api/payloads";
import { useCommand, useScreen } from "@/api/useScreen";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Field } from "@/components/ui/field";
import { Input, Select } from "@/components/ui/input";
import { DataTable, type Column } from "@/components/ui/table";
import { Tabs } from "@/components/ui/tabs";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";

type Screen = TaxonomiesPayload;
type Item = TaxonomyItem;

/**
 * The five taxonomies, one tab each (LLD §11.3 `admin/taxonomies`).
 *
 * Programs carry two things the others do not: the branches they admit, and the
 * shape of the enrollment they are. "BTech Dual Major" and "BTech-MTech Dual
 * Degree" are programmes admitted into, so whether a student holds two
 * disciplines is settled by which programme they are in, not by a flag on
 * their profile (the design review §4.32, amended here).
 */
const KINDS = [
  { id: "programs", label: "Programs" },
  { id: "branches", label: "Branches" },
  { id: "minors", label: "Minors" },
  { id: "sectors", label: "Sectors" },
  { id: "round_types", label: "Round types" },
] as const;

type Kind = (typeof KINDS)[number]["id"];

export function Taxonomies() {
  const screen = useScreen("admin/taxonomies");
  const [kind, setKind] = useState<Kind>("programs");

  if (screen.isPending) return <ListSkeleton />;
  if (screen.isError) {
    return <ErrorState error={screen.error} onRetry={() => void screen.refetch()} />;
  }

  const data = payload<Screen>(screen.data);
  const items = data[kind] ?? [];

  return (
    <>
      <PageHeader
        title="Taxonomies"
        subtitle="The controlled vocabularies every profile, job, and rule draws from."
      />
      <Tabs
        tabs={KINDS.map((entry) => ({
          id: entry.id,
          label: entry.label,
          badge: (data[entry.id] ?? []).length,
        }))}
        active={kind}
        onChange={setKind}
      />
      <TaxonomyTab key={kind} kind={kind} items={items} data={data} />
    </>
  );
}

function TaxonomyTab({ kind, items, data }: { kind: Kind; items: Item[]; data: Screen }) {
  const upsert = useCommand("upsert_taxonomy_item");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [branchIds, setBranchIds] = useState<string[]>([]);
  const [structure, setStructure] = useState("single");
  const [primaryDegree, setPrimaryDegree] = useState("");
  const [secondaryDegree, setSecondaryDegree] = useState("");
  const branches = data.branches ?? [];
  const mappings = data.program_branches ?? [];
  // A component degree is itself a plain degree, so a combined programme is
  // never built out of another combined one.
  const degrees = (data.programs ?? []).filter(
    (item) => (item.structure ?? "single") === "single" && item.id !== editingId,
  );
  const combined = structure !== "single";

  function reset() {
    setEditingId(null);
    setName("");
    setBranchIds([]);
    setStructure("single");
    setPrimaryDegree("");
    setSecondaryDegree("");
  }

  function editItem(item: Item) {
    setEditingId(item.id);
    setName(item.name);
    setBranchIds(
      kind === "programs"
        ? mappings.filter((row) => row.program_id === item.id).map((row) => row.branch_id)
        : [],
    );
    setStructure(item.structure ?? "single");
    setPrimaryDegree(item.primary_degree_id ?? "");
    setSecondaryDegree(item.secondary_degree_id ?? "");
  }

  function submit() {
    upsert.mutate(
      {
        input: {
          kind,
          ...(editingId ? { item_id: editingId } : {}),
          name: name.trim(),
          action: "upsert",
          is_active: true,
          ...(kind === "programs"
            ? {
                branch_ids: branchIds,
                structure: structure as "single" | "dual_major" | "dual_degree",
                primary_degree_id: combined ? primaryDegree : null,
                secondary_degree_id: combined ? secondaryDegree : null,
              }
            : {}),
        },
      },
      {
        onSuccess: reset,
      },
    );
  }

  function toggleActive(item: Item) {
    upsert.mutate({
      input: {
        kind,
        item_id: item.id,
        name: item.name,
        action: "upsert",
        is_active: !item.is_active,
      },
    });
  }

  const columns: Column<Item>[] = [
    { key: "name", header: "Name", cell: (item) => item.name },
    ...(kind === "programs"
      ? [
          {
            key: "branches",
            header: "Branches",
            cell: (item: Item) => {
              const names = mappings
                .filter((row) => row.program_id === item.id)
                .map(
                  (row) => branches.find((branch) => branch.id === row.branch_id)?.name,
                )
                .filter(Boolean);
              return names.length ? (
                names.join(", ")
              ) : (
                <span className="text-muted-foreground">None mapped</span>
              );
            },
          },
        ]
      : []),
    {
      key: "active",
      header: "Status",
      width: "160px",
      cell: (item) => (
        <span className={item.is_active ? "text-foreground" : "text-muted-foreground"}>
          {item.is_active ? "Active" : "Inactive"}
        </span>
      ),
    },
    {
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      width: "120px",
      numeric: true,
      cell: (item) => (
        <div className="flex justify-end gap-gap-tight">
          <Button variant="ghost" size="sm" onClick={() => editItem(item)}>
            Edit
          </Button>
          <Button variant="ghost" size="sm" onClick={() => toggleActive(item)}>
            {item.is_active ? "Deactivate" : "Reactivate"}
          </Button>
        </div>
      ),
    },
  ];

  return (
    <div className="flex flex-col gap-section-margin">
      {upsert.isError ? <ErrorState error={upsert.error} title="Could not save" /> : null}

      <Card>
        <CardHeader>
          <CardTitle>{editingId ? "Edit item" : "Add an item"}</CardTitle>
        </CardHeader>
        <CardBody className="flex flex-col gap-gap-lg">
          <div className="flex flex-wrap items-end gap-gap-lg">
            <Field label="Name" className="min-w-64 flex-1">
              {(field) => (
                <Input
                  {...field}
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="e.g. Computer Science and Engineering"
                />
              )}
            </Field>
            <Button
              variant="primary"
              icon={<Plus className="h-4 w-4" />}
              disabled={
                !name.trim() ||
                (kind === "programs" && combined && (!primaryDegree || !secondaryDegree))
              }
              loading={upsert.isPending}
              onClick={submit}
            >
              {editingId ? "Save" : "Add"}
            </Button>
            {editingId ? (
              <Button variant="ghost" onClick={reset}>Cancel</Button>
            ) : null}
          </div>

          {kind === "programs" ? (
            <>
              <Field
                label="What this program enrols a student in"
                hint="A dual major reads both disciplines from one degree; a dual degree reads its second from the postgraduate one."
              >
                {(input) => (
                  <Select
                    {...input}
                    value={structure}
                    onChange={(event: ChangeEvent<HTMLSelectElement>) =>
                      setStructure(event.target.value)
                    }
                  >
                    <option value="single">One discipline</option>
                    <option value="dual_major">Dual major — two disciplines</option>
                    <option value="dual_degree">Dual degree — undergraduate and postgraduate</option>
                  </Select>
                )}
              </Field>
              {combined ? (
                <div className="grid gap-gap-lg sm:grid-cols-2">
                  <Field label="Primary discipline comes from">
                    {(input) => (
                      <Select
                        {...input}
                        value={primaryDegree}
                        onChange={(event: ChangeEvent<HTMLSelectElement>) =>
                          setPrimaryDegree(event.target.value)
                        }
                      >
                        <option value="">Select a degree…</option>
                        {degrees.map((item) => (
                          <option key={item.id} value={item.id}>{item.name}</option>
                        ))}
                      </Select>
                    )}
                  </Field>
                  <Field label="Second discipline comes from">
                    {(input) => (
                      <Select
                        {...input}
                        value={secondaryDegree}
                        onChange={(event: ChangeEvent<HTMLSelectElement>) =>
                          setSecondaryDegree(event.target.value)
                        }
                      >
                        <option value="">Select a degree…</option>
                        {degrees.map((item) => (
                          <option key={item.id} value={item.id}>{item.name}</option>
                        ))}
                      </Select>
                    )}
                  </Field>
                </div>
              ) : null}
              <Field label="Branches this program admits">
                {() => (
                  branches.length === 0 ? (
                    <p className="text-body-sm text-muted-foreground">
                      Add a branch taxonomy item before mapping a programme.
                    </p>
                  ) : (
                  <div className="flex flex-wrap gap-gap-lg">
                    {branches.map((branch) => (
                      <label
                        key={branch.id}
                        className="flex items-center gap-gap-md text-body-md text-foreground"
                      >
                        <Checkbox
                          checked={branchIds.includes(branch.id)}
                          onChange={(event) =>
                            setBranchIds((prev) =>
                              event.target.checked
                                ? [...prev, branch.id]
                                : prev.filter((id) => id !== branch.id),
                            )
                          }
                        />
                        {branch.name}
                      </label>
                    ))}
                  </div>
                  )
                )}
              </Field>
            </>
          ) : null}
        </CardBody>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{items.length} item{items.length === 1 ? "" : "s"}</CardTitle>
        </CardHeader>
        <DataTable
          columns={columns}
          rows={items}
          rowKey={(item) => item.id}
          empty={
            <CardBody>
              <EmptyState message="Nothing here yet. Add the first item above." />
            </CardBody>
          }
        />
      </Card>
    </div>
  );
}

function ListSkeleton() {
  return (
    <div className="flex flex-col gap-gap-lg">
      <Skeleton className="h-9 w-64" />
      <Skeleton className="h-10 w-full" />
      <Skeleton className="h-64 w-full" />
    </div>
  );
}
