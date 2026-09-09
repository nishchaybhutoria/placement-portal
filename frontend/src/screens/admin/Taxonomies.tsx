import { Plus } from "lucide-react";
import { useState } from "react";

import { payload, type TaxonomiesPayload, type TaxonomyItem } from "@/api/payloads";
import { useCommand, useScreen } from "@/api/useScreen";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { DataTable, type Column } from "@/components/ui/table";
import { Tabs } from "@/components/ui/tabs";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";

type Screen = TaxonomiesPayload;
type Item = TaxonomyItem;

/**
 * The five taxonomies, one tab each (LLD §11.3 `admin/taxonomies`).
 *
 * Programs carry one thing the others do not: the branches they admit, edited
 * here because there is nowhere else they can be. Whether a *student* holds two
 * of those branches at once is a fact about the student and lives on their
 * profile, not here (the design review §4.32).
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
  const branches = data.branches ?? [];
  const mappings = data.program_branches ?? [];

  function reset() {
    setEditingId(null);
    setName("");
    setBranchIds([]);
  }

  function editItem(item: Item) {
    setEditingId(item.id);
    setName(item.name);
    setBranchIds(
      kind === "programs"
        ? mappings.filter((row) => row.program_id === item.id).map((row) => row.branch_id)
        : [],
    );
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
          ...(kind === "programs" ? { branch_ids: branchIds } : {}),
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
              disabled={!name.trim()}
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
