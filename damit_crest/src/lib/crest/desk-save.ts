import { deskFileName, deskFileText } from "./desk-file.ts";
import { saveText } from "./save.ts";
import { useDesk } from "./store.ts";

/** "Save desk to file" (also the command palette's): the note to show, or the error. */
export async function saveDeskFile(): Promise<{ note?: string; error?: string }> {
  const { dams, activeId } = useDesk.getState();
  const r = await saveText(deskFileName(), deskFileText(dams, activeId), "application/json");
  if (r.status === "error") return { error: `The desk file was not saved: ${r.message}` };
  if (r.status === "saved")
    return {
      note: `Desk saved to a file: ${dams.length} dam${dams.length === 1 ? "" : "s"}${r.path ? ` (${r.path})` : ""}. Keep it somewhere safe; open it again with "Open desk file or dam.json".`,
    };
  return {};
}
