import { render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { Sidebar } from "@/components/sidebar";
import { InsightsRedirect } from "@/pages/insights";

function nav(code: string | undefined, admin: boolean, at = "/") {
  return render(
    <MemoryRouter initialEntries={[at]}>
      <Sidebar code={code} admin={admin} collapsed={false} onToggle={() => undefined} />
    </MemoryRouter>,
  );
}

const items = (section: string) => {
  const heading = screen.getByText(section, { selector: "p" });
  const links = within(heading.parentElement as HTMLElement).getAllByRole("link");
  return links.map((link) => link.textContent);
};

describe("the navigation", () => {
  it("groups a project's pages as Overview, Operations and Platform", () => {
    nav("demo", true);
    expect(items("Overview")).toEqual(["Home", "Pipelines", "Catalog"]);
    expect(items("Operations")).toEqual(["Runs", "Scheduled runs", "Held and paused", "Uploads", "Console", "Maintenance"]);
    expect(items("Platform")).toEqual(["Projects", "System health", "Agents", "Administration"]);
    expect(screen.queryByText("Insights")).toBeNull();
    expect(screen.queryByText("Project", { selector: "p" })).toBeNull();
  });

  it("leaves out the project's pages until a project is open, and administration for others", () => {
    nav(undefined, false);
    expect(items("Overview")).toEqual(["Home"]);
    expect(screen.queryByText("Operations")).toBeNull();
    expect(items("Platform")).toEqual(["Projects", "System health", "Agents"]);
  });
});

describe("the current page", () => {
  it("marks Home, not Projects, on a project's own address", () => {
    nav("demo", true, "/projects/demo");
    expect(screen.getByRole("link", { name: "Home" }).getAttribute("aria-current")).toBe("page");
    expect(screen.getByRole("link", { name: "Projects" }).getAttribute("aria-current")).toBeNull();
  });

  it("marks Projects on the list of projects", () => {
    nav("demo", true, "/projects");
    expect(screen.getByRole("link", { name: "Projects" }).getAttribute("aria-current")).toBe("page");
    expect(screen.getByRole("link", { name: "Home" }).getAttribute("aria-current")).toBeNull();
  });
});

describe("the old Insights address", () => {
  it("opens the project's Home with the filters it carried", () => {
    render(
      <MemoryRouter initialEntries={["/projects/demo/insights?pipeline=ORDERS&from=2026-01-01"]}>
        <Routes>
          <Route path="projects/:project/insights" element={<InsightsRedirect />} />
          <Route path="projects/:project" element={<p>project home</p>} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByText("project home")).toBeTruthy();
  });
});
