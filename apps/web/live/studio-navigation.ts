import { expect, type Page } from "@playwright/test";

/** Reach a permitted destination through the real hierarchical Studio navigation. */
export async function openStudioDestination(page: Page, name: string): Promise<void> {
  const navigation = page.getByRole("navigation", { name: "Primary navigation", exact: true });
  const search = page.getByRole("searchbox", { name: "Find a workspace", exact: true });
  await search.fill(name);
  const destination = navigation.getByRole("button", { name, exact: true });
  await expect(destination).toBeVisible();
  await destination.click();
  await search.clear();
}
