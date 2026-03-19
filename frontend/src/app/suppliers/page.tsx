"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { AppShell } from "@/components/app-shell";
import { PageState } from "@/components/page-state";
import { api } from "@/lib/api";
import type { Supplier } from "@/lib/types";

const emptySupplier: Supplier = {
  code: "",
  name: "",
  global_id: "",
  email: "",
  phone: "",
  special_instructions: "",
};

export default function SuppliersPage() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [draft, setDraft] = useState<Supplier>(emptySupplier);
  const [page] = useState(1);

  const params = useMemo(() => {
    const nextParams = new URLSearchParams();
    if (search) nextParams.set("search", search);
    nextParams.set("page", String(page));
    nextParams.set("page_size", "10");
    return nextParams;
  }, [page, search]);

  const suppliers = useQuery({
    queryKey: ["suppliers", params.toString()],
    queryFn: () => api.getSuppliers(params),
  });

  const createSupplier = useMutation({
    mutationFn: () => api.createSupplier(draft),
    onSuccess: async () => {
      setDraft(emptySupplier);
      await queryClient.invalidateQueries({ queryKey: ["suppliers"] });
    },
  });

  const updateSupplier = useMutation({
    mutationFn: (supplier: Supplier) => api.updateSupplier(supplier.code, supplier),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["suppliers"] });
    },
  });

  return (
    <AppShell>
      <div className="grid gap-6 lg:grid-cols-[1.7fr_1fr]">
        <div className="rounded-4xl border border-white/70 bg-white/90 p-6 shadow-panel">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-2xl font-semibold text-slate-900">ניהול ספקים</h2>
            <input
              className="rounded-2xl border border-slate-200 px-4 py-3 text-sm"
              onChange={(event) => setSearch(event.target.value)}
              placeholder="חיפוש לפי קוד, שם, ח.פ או אימייל"
              value={search}
            />
          </div>

          <div className="mt-6 space-y-4">
            {suppliers.isLoading ? (
              <PageState title="טוען ספקים" body="מושך את רשימת הספקים מה-API החדש." />
            ) : (
              suppliers.data?.items.map((supplier) => (
                <div key={supplier.code} className="rounded-3xl border border-slate-200 p-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <div className="font-semibold text-slate-900">
                        {supplier.name} ({supplier.code})
                      </div>
                      <div className="mt-1 text-sm text-slate-500">
                        ח.פ: {supplier.global_id || "-"} | אימייל: {supplier.email || "-"} | טלפון:{" "}
                        {supplier.phone || "-"}
                      </div>
                    </div>
                    <button
                      className="rounded-full bg-slate-900 px-4 py-2 text-sm text-white"
                      onClick={() => updateSupplier.mutate(supplier)}
                      type="button"
                    >
                      שמור
                    </button>
                  </div>
                  <textarea
                    className="mt-4 min-h-28 w-full rounded-2xl border border-slate-200 px-4 py-3 text-sm"
                    onChange={(event) =>
                      suppliers.data &&
                      queryClient.setQueryData(
                        ["suppliers", params.toString()],
                        {
                          ...suppliers.data,
                          items: suppliers.data.items.map((item) =>
                            item.code === supplier.code ? { ...item, special_instructions: event.target.value } : item,
                          ),
                        },
                      )
                    }
                    value={supplier.special_instructions}
                  />
                </div>
              ))
            )}
          </div>
        </div>

        <div className="rounded-4xl border border-white/70 bg-white/90 p-6 shadow-panel">
          <h3 className="text-xl font-semibold text-slate-900">הוסף ספק חדש</h3>
          <div className="mt-5 grid gap-3">
            {[
              ["code", "קוד ספק"],
              ["name", "שם"],
              ["global_id", "ח.פ / עוסק"],
              ["email", "אימייל"],
              ["phone", "טלפון"],
            ].map(([key, label]) => (
              <input
                key={key}
                className="rounded-2xl border border-slate-200 px-4 py-3 text-sm"
                onChange={(event) => setDraft((current) => ({ ...current, [key]: event.target.value }))}
                placeholder={label}
                value={draft[key as keyof Supplier] as string}
              />
            ))}
            <textarea
              className="min-h-32 rounded-2xl border border-slate-200 px-4 py-3 text-sm"
              onChange={(event) => setDraft((current) => ({ ...current, special_instructions: event.target.value }))}
              placeholder="הוראות חילוץ מיוחדות"
              value={draft.special_instructions}
            />
            <button
              className="rounded-2xl bg-slate-950 px-5 py-3 text-white disabled:bg-slate-400"
              disabled={!draft.code || !draft.name || !draft.global_id || createSupplier.isPending}
              onClick={() => createSupplier.mutate()}
              type="button"
            >
              {createSupplier.isPending ? "שומר..." : "הוסף ספק"}
            </button>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
