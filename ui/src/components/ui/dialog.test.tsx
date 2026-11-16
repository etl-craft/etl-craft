import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it } from "vitest";
import { useState } from "react";
import { Dialog } from "@/components/ui/dialog";

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  HTMLDialogElement.prototype.close = function () { this.open = false; };
});

it("keeps a reopened dialog open when its previous close event arrives late", () => {
  function Example() {
    const [open, setOpen] = useState(false);
    return <>
      <button onClick={() => setOpen(true)}>Inspect task</button>
      <Dialog open={open} onClose={() => setOpen(false)} labelledBy="dialog-title">
        <h2 id="dialog-title">Task definition</h2>
        <button onClick={() => setOpen(false)}>Close details</button>
      </Dialog>
    </>;
  }
  render(<Example/>);
  fireEvent.click(screen.getByRole("button", {name:"Inspect task"}));
  const dialog = screen.getByRole("dialog");
  fireEvent.click(screen.getByRole("button", {name:"Close details"}));
  fireEvent.click(screen.getByRole("button", {name:"Inspect task"}));
  fireEvent(dialog, new Event("close"));
  expect(screen.getByRole("dialog", {name:"Task definition"})).toBeVisible();
  (dialog as HTMLDialogElement).open = false;
  fireEvent(dialog, new Event("close"));
  expect(screen.queryByRole("dialog")).toBeNull();
});
