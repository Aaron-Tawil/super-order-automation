"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { AppShell } from "@/components/app-shell";
import { PageState } from "@/components/page-state";
import { api } from "@/lib/api";
import type { Item } from "@/lib/types";

const emptyItem: Item = {
  barcode: "",
  name: "",
  item_code: "",
  note: "",
};

export default function ItemsPage() {
  const queryClient = useQueryClient();
  const [query, setQuery] = useState("");
  const [draft, setDraft] = useState<Item>(emptyItem);
  const [deleteInput, setDeleteInput] = useState("");

  const items = useQuery({
    queryKey: ["items", query],
    queryFn: () => api.searchItems(query),
    enabled: query.length > 0,
  });

  const createItem = useMutation({
    mutationFn: () => api.createItem(draft as Item),
    onSuccess: async () => {
      setDraft(emptyItem);
      await queryClient.invalidateQueries({ queryKey: ["items"] });
    },
  });

  const deleteItems = useMutation({
    mutationFn: () =>
      api.deleteItems(
        deleteInput
          .split(",")
          .map((value) => value.trim())
          .filter(Boolean),
      ),
    onSuccess: async () => {
      setDeleteInput("");
      await queryClient.invalidateQueries({ queryKey: ["items"] });
    },
  });

  return (
    <AppShell>
      <div className="grid gap-6 lg:grid-cols-[1.6fr_1fr]">
        <div className="rounded-[2rem] border border-white/70 bg-white/90 p-6 shadow-panel">
          <h2 className="text-2xl font-semibold text-slate-900">חיפוש ועריכת פריטים</h2>
          <input
            className="mt-5 w-full rounded-2xl border border-slate-200 px-4 py-3 text-sm"
            onChange={(event) => setQuery(event.target.value)}
            placeholder="חפש לפי ברקוד או שם"
            value={query}
          />

          <div className="mt-6 space-y-3">
            {!query ? (
              <PageState title="חפש פריט" body="הקלד ברקוד או שם כדי למשוך תוצאות מה-API." />
            ) : items.isLoading ? (
              <PageState title="טוען פריטים" body="מבצע חיפוש בקטלוג הפריטים." />
            ) : items.data?.length ? (
              items.data.map((item) => (
                <div key={item.barcode} className="rounded-3xl border border-slate-200 p-4">
                  <div className="font-semibold text-slate-900">
                    {item.name} ({item.barcode})
                  </div>
                  <div className="mt-2 text-sm text-slate-600">
                    קוד פריט: {item.item_code || "-"} | הערה: {item.note || "-"}
                  </div>
                </div>
              ))
            ) : (
              <PageState title="אין תוצאות" body="לא נמצאו פריטים לחיפוש שהוזן." />
            )}
          </div>
        </div>

        <div className="space-y-6">
          <div className="rounded-[2rem] border border-white/70 bg-white/90 p-6 shadow-panel">
            <h3 className="text-xl font-semibold text-slate-900">הוסף פריט</h3>
            <div className="mt-5 grid gap-3">
              {[
                ["barcode", "ברקוד"],
                ["name", "שם"],
                ["item_code", "קוד פריט"],
                ["note", "הערה"],
              ].map(([key, label]) => (
                <input
                  key={key}
                  className="rounded-2xl border border-slate-200 px-4 py-3 text-sm"
                  onChange={(event) => setDraft((current) => ({ ...current, [key]: event.target.value }))}
                  placeholder={label}
                  value={(draft[key as keyof Item] as string) || ""}
                />
              ))}
              <button
                className="rounded-2xl bg-slate-950 px-5 py-3 text-white disabled:bg-slate-400"
                disabled={!draft.barcode || !draft.name || !draft.item_code || createItem.isPending}
                onClick={() => createItem.mutate()}
                type="button"
              >
                {createItem.isPending ? "שומר..." : "הוסף פריט"}
              </button>
            </div>
          </div>

          <div className="rounded-[2rem] border border-white/70 bg-white/90 p-6 shadow-panel">
            <h3 className="text-xl font-semibold text-slate-900">מחיקת פריטים באצווה</h3>
            <textarea
              className="mt-5 min-h-28 w-full rounded-2xl border border-slate-200 px-4 py-3 text-sm"
              onChange={(event) => setDeleteInput(event.target.value)}
              placeholder="הדבק ברקודים מופרדים בפסיקים"
              value={deleteInput}
            />
            <button
              className="mt-4 rounded-2xl border border-rose-200 bg-rose-50 px-5 py-3 text-rose-800 disabled:opacity-50"
              disabled={!deleteInput || deleteItems.isPending}
              onClick={() => deleteItems.mutate()}
              type="button"
            >
              {deleteItems.isPending ? "מוחק..." : "מחק פריטים"}
            </button>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
