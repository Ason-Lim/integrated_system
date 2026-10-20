import type { ChipItem, ChipMode, ChipsBlock } from "../types/blocks";
import { toChip } from "../api/adapt";
import { useChatActions } from "./ChatActions";
import { cx } from "../lib/format";

/** mode=chip → ChatIn.chip (서버가 규칙으로 즉시 재정렬) / mode=message → 자연어 메시지로 전송 */
export function ChipButton({ item, mode, small }: { item: ChipItem; mode: ChipMode; small?: boolean }) {
  const { send, busy } = useChatActions();
  const value = item.value ?? item.label;
  return (
    <button type="button" disabled={busy}
      className={cx("chip-btn", small && "px-3 py-1 text-[13px]")}
      onClick={() => send(mode === "chip" ? { chip: value } : { message: value }, item.label)}>
      {item.label}
    </button>
  );
}

export function ChipsRow({ block }: { block: ChipsBlock }) {
  const mode = block.data.mode ?? "message";
  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {block.data.items.map((it) => {
        const c = toChip(it);
        return <ChipButton key={c.label} item={c} mode={mode} />;
      })}
    </div>
  );
}
