import { MemoryRouter } from "react-router-dom";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { AppLink } from "@/components/navigation";
import { runPath, taskPath } from "@/lib/routes";

afterEach(cleanup);
it("opens external and documentation links with isolated openers and an accessible warning", () => {
  render(<MemoryRouter><AppLink to="https://docs.example.org">External</AppLink><AppLink documentation to="/documentation">Documentation</AppLink></MemoryRouter>);
  for(const label of ["External","Documentation"]) {
    const link=screen.getByRole("link",{name:`${label} (opens in a new tab)`});
    expect(link).toHaveAttribute("target","_blank"); expect(link).toHaveAttribute("rel","noopener noreferrer");
  }
});
it("keeps run and task inspection in the current tab and honours the router base", () => {
  render(<MemoryRouter basename="/ui" initialEntries={["/ui/"]}><AppLink to={runPath("demo","load",8)}>Run</AppLink><AppLink to={taskPath("demo","load","copy")}>Task</AppLink></MemoryRouter>);
  for(const name of ["Run","Task"]) {
    const link=screen.getByRole("link",{name});expect(link).not.toHaveAttribute("target");
    expect(link.getAttribute("href")).toMatch(/^\/ui\/projects\/demo\//);
  }
});
