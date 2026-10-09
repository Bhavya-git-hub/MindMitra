import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Heart } from "lucide-react";
import { describe, expect, it, vi } from "vitest";
import { useForm } from "react-hook-form";

import { StatCard } from "@/components/cards/stat-card";
import { BarSeriesChart, DonutChart, Sparkline, TrendChart } from "@/components/charts";
import {
  CheckboxField,
  SelectField,
  SubmitButton,
  TextareaField,
  TextField,
} from "@/components/forms/fields";
import { useModal } from "@/components/providers/modal-provider";
import { EmptyState } from "@/components/states/empty-state";
import { ErrorState } from "@/components/states/error-state";
import { InlineAlert } from "@/components/states/inline-alert";
import { LoadingState, PageSkeleton } from "@/components/states/loading-state";
import { Form } from "@/components/ui/form";
import { notify } from "@/lib/toast";

import { renderWithApp } from "../helpers/render";

describe("toast system", () => {
  it("shows success and error toasts", async () => {
    renderWithApp(<div />);
    notify.success("Saved", "Your changes are safe.");
    expect(await screen.findByText("Saved")).toBeInTheDocument();
    expect(screen.getByText("Your changes are safe.")).toBeInTheDocument();
    notify.error("That didn't work");
    expect(await screen.findByText("That didn't work")).toBeInTheDocument();
  });
});

function ModalDemo({ onResult }: { onResult: (v: boolean) => void }) {
  const modal = useModal();
  return (
    <>
      <button
        onClick={async () =>
          onResult(
            await modal.confirm({
              title: "Delete it?",
              description: "Cannot be undone.",
              confirmLabel: "Delete",
              destructive: true,
            }),
          )
        }
      >
        ask
      </button>
      <button
        onClick={() =>
          modal.open({ title: "Hello", content: (close) => <button onClick={close}>done</button> })
        }
      >
        open
      </button>
    </>
  );
}

describe("modal system", () => {
  it("resolves true on confirm and false on cancel", async () => {
    const results: boolean[] = [];
    renderWithApp(<ModalDemo onResult={(v) => results.push(v)} />);
    const user = userEvent.setup();

    await user.click(screen.getByText("ask"));
    const dialog = await screen.findByRole("alertdialog", { name: "Delete it?" });
    expect(within(dialog).getByText("Cannot be undone.")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(results).toEqual([true]));

    await user.click(screen.getByText("ask"));
    await user.click(await screen.findByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(results).toEqual([true, false]));
  });

  it("cancels on Escape and returns focus to the trigger", async () => {
    const results: boolean[] = [];
    renderWithApp(<ModalDemo onResult={(v) => results.push(v)} />);
    const user = userEvent.setup();
    const trigger = screen.getByText("ask");
    await user.click(trigger);
    await screen.findByRole("alertdialog");
    await user.keyboard("{Escape}");
    await waitFor(() => expect(results).toEqual([false]));
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("opens a general dialog whose content can close it", async () => {
    renderWithApp(<ModalDemo onResult={() => {}} />);
    const user = userEvent.setup();
    await user.click(screen.getByText("open"));
    const dialog = await screen.findByRole("dialog", { name: "Hello" });
    await user.click(within(dialog).getByText("done"));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});

interface V {
  name: string;
  about: string;
  stream: string;
  agree: boolean;
}

function FieldsDemo({ onSubmit }: { onSubmit: (v: V) => void }) {
  const form = useForm<V>({ defaultValues: { name: "", about: "", stream: "", agree: false } });
  return (
    <Form {...form}>
      <form onSubmit={form.handleSubmit(onSubmit)}>
        <TextField<V> name="name" label="Name" description="What we call you" />
        <TextareaField<V> name="about" label="About" />
        <SelectField<V>
          name="stream"
          label="Stream"
          options={[{ value: "sci", label: "Science" }]}
        />
        <CheckboxField<V> name="agree" label="Remind me" />
        <SubmitButton pending={false}>Save</SubmitButton>
      </form>
    </Form>
  );
}

describe("form fields", () => {
  it("connect labels and descriptions to controls", () => {
    render(<FieldsDemo onSubmit={() => {}} />);
    const name = screen.getByLabelText("Name");
    expect(name).toHaveAccessibleDescription("What we call you");
    expect(screen.getByLabelText("About").tagName).toBe("TEXTAREA");
    expect(screen.getByRole("checkbox", { name: "Remind me" })).toBeInTheDocument();
  });

  it("collects values", async () => {
    const onSubmit = vi.fn();
    render(<FieldsDemo onSubmit={onSubmit} />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Name"), "Asha");
    await user.type(screen.getByLabelText("About"), "Tired but ok");
    await user.click(screen.getByRole("combobox", { name: "Stream" }));
    await user.click(await screen.findByRole("option", { name: "Science" }));
    await user.click(screen.getByRole("checkbox", { name: "Remind me" }));
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(onSubmit.mock.calls[0]?.[0]).toEqual({
      name: "Asha",
      about: "Tired but ok",
      stream: "sci",
      agree: true,
    });
  });

  it("SubmitButton shows progress and blocks double submits", () => {
    render(
      <SubmitButton pending pendingLabel="Saving…">
        Save
      </SubmitButton>,
    );
    const button = screen.getByRole("button", { name: "Saving…" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
  });
});

describe("states", () => {
  it("LoadingState is announced politely", () => {
    render(<LoadingState label="Fetching…" />);
    expect(screen.getByRole("status")).toHaveTextContent("Fetching…");
  });

  it("PageSkeleton announces loading", () => {
    render(<PageSkeleton />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading your page");
  });

  it("ErrorState offers a retry and a support reference, never internals", async () => {
    const retry = vi.fn();
    render(<ErrorState onRetry={retry} reference="req-42" />);
    expect(screen.getByRole("alert")).toHaveTextContent("Reference: req-42");
    await userEvent.setup().click(screen.getByRole("button", { name: "Try again" }));
    expect(retry).toHaveBeenCalled();
  });

  it("EmptyState and InlineAlert render their content", () => {
    render(
      <>
        <EmptyState icon={Heart} title="Nothing yet" description="Add one" />
        <InlineAlert tone="destructive">Oops</InlineAlert>
        <InlineAlert tone="success">Yay</InlineAlert>
      </>,
    );
    expect(screen.getByRole("heading", { name: "Nothing yet" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Oops"); // urgent: assertive
    expect(screen.getByRole("status")).toHaveTextContent("Yay"); // calm: polite
  });
});

describe("cards and charts", () => {
  it("StatCard states the trend in words, not colour alone", () => {
    render(<StatCard label="Check-ins" value={5} trend="up" trendLabel="vs last week" />);
    expect(screen.getByText("up vs last week")).toBeInTheDocument();
  });

  it("every chart carries its data as a screen-reader table", () => {
    render(
      <>
        <TrendChart
          title="Mood"
          data={[
            { day: "Mon", mood: 3 },
            { day: "Tue", mood: 4 },
          ]}
          xKey="day"
          series={[{ key: "mood", label: "Mood" }]}
        />
        <BarSeriesChart
          title="Sessions"
          data={[{ wk: "1", done: 8 }]}
          xKey="wk"
          series={[{ key: "done", label: "Done" }]}
        />
        <DonutChart
          title="Support"
          data={[
            { name: "Peers", value: 3 },
            { name: "Counsellor", value: 1 },
          ]}
        />
      </>,
    );
    const mood = screen.getByRole("table", { name: "Mood" });
    expect(within(mood).getByRole("rowheader", { name: "Tue" })).toBeInTheDocument();
    expect(
      within(mood)
        .getAllByRole("cell")
        .map((c) => c.textContent),
    ).toEqual(["3", "4"]);
    expect(screen.getByRole("table", { name: "Sessions" })).toBeInTheDocument();
    // The donut legend is real text with shares.
    expect(screen.getByText("3 (75%)")).toBeInTheDocument();
    // The drawing itself is hidden from assistive technology.
    expect(
      screen.getByRole("figure", { name: "Mood" }).querySelector("[aria-hidden='true']"),
    ).not.toBeNull();
  });

  it("Sparkline is decorative", () => {
    const { container } = render(<Sparkline values={[1, 2, 3]} />);
    expect(container.firstElementChild).toHaveAttribute("aria-hidden", "true");
  });
});
