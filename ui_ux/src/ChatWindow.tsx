import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ArrowUp, ArrowRight, Plus, Sparkles, ShoppingBag, Utensils, Square, Gift, Cookie, Leaf, type LucideIcon } from 'lucide-react';
import { BlockRenderer } from './components/BlockRenderer';
import { ProductDetail } from './components/ProductDetail';
import { FlowStepper } from './components/FlowStepper';
import { ChatActions, type ChatActionsValue } from './components/ChatActions';
import type { FlowStep, SendPayload } from './state/useConversation';
import type { Message } from './types';
import type { Candidate } from './types/blocks';
import { sendChat } from './api/client';

// ── 홈 화면 예시 질문: src/data/trend_examples_YYYY-MM-DD.json 중 최신 파일을 읽는다 ──
// 파일은 scripts/update_trend_examples.py가 매일 만든다. (dev 서버는 새 파일이 생기면 자동 반영, 배포는 다시 빌드)
type TrendExample = { category: string; icon?: string; keyword?: string; question: string };
type Example = { icon: LucideIcon; label: string; text: string; note: string };

const ICONS: Record<string, LucideIcon> = { Gift, Cookie, Utensils, Leaf, ShoppingBag };

const FALLBACK_EXAMPLES: Example[] = [
    { icon: Gift, label: '선물용', text: '부모님 선물로 좋은 식품 추천해줘', note: '받는 분 취향까지 고려해서' },
    { icon: Cookie, label: '간식/디저트', text: '두바이 쫀득쿠키 추천해줘', note: '가격부터 배송까지 한 번에' },
    { icon: Utensils, label: '레시피/요리', text: '파스타 레시피로 장보기', note: '있는 재료는 빼고, 필요한 만큼' },
    { icon: Leaf, label: '캠핑', text: '캠핑 갈 때 챙길 먹거리 추천해줘', note: '보관·조리 편의까지 함께' }
];

const trendFiles = import.meta.glob<TrendExample[]>('./data/trend_examples_*.json', { eager: true, import: 'default' });

// 정상 파일: 질문이 3개 이상이고 키워드가 서로 겹치지 않는 파일 (같은 키워드만 반복된 파일은 건너뜀)
function isUsable(rows: unknown): rows is TrendExample[] {
    if (!Array.isArray(rows) || rows.length < 3) return false;
    const ok = rows.filter(r => r && typeof r.question === 'string' && r.question.trim() && typeof r.category === 'string');
    const keys = new Set(ok.map(r => (r.keyword || r.question).trim()));
    return ok.length >= 3 && keys.size === ok.length;
}

function loadExamples(): { examples: Example[]; date: string | null } {
    const paths = Object.keys(trendFiles).sort().reverse(); // 파일명 날짜 기준 최신순
    for (const path of paths) {
        const rows = trendFiles[path];
        if (!isUsable(rows)) continue;
        const date = path.match(/(\d{4})-(\d{2})-(\d{2})/);
        const mmdd = date ? `${Number(date[2])}/${Number(date[3])}` : '';
        return {
            date: date ? date[0] : null,
            examples: rows.slice(0, 4).map(r => ({
                icon: ICONS[r.icon ?? ''] ?? ShoppingBag,
                label: r.category,
                text: r.question.trim(),
                note: r.keyword ? `${mmdd} 급상승 키워드 · ${r.keyword}` : `${mmdd} 트렌드`,
            })),
        };
    }
    return { examples: FALLBACK_EXAMPLES, date: null };
}

const { examples, date: examplesDate } = loadExamples();

export default function ChatWindow() {
    const [messages, setMessages] = useState<Message[]>([]);
    const [input, setInput] = useState('');
    const [sessionId, setSessionId] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const [detail, setDetail] = useState<Candidate | null>(null);
    const [purchasing, setPurchasing] = useState(false);
    const controller = useRef<AbortController | null>(null);
    const locked = useRef(false);
    const bottom = useRef<HTMLDivElement>(null);

    // 대화 진행 상태로 현재 단계 추정: 입력 → 조건 확인 → 후보 비교 → 상품 판단 → 구매 연결
    const step: FlowStep = (() => {
        if (detail) return purchasing ? 5 : 4;
        if (!messages.length) return 1;
        if (busy) return 2;
        const assistantTurns = messages.filter(m => m.role === 'assistant').length;
        if (assistantTurns <= 1) return 3;
        if (assistantTurns === 2) return 4;
        return 5;
    })();

    useEffect(() => { bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }); }, [messages, busy, error]);
    useEffect(() => () => controller.current?.abort(), []);

    // 자연어 메시지 · 칩 · 조건 선택(answers) 모두 이 함수로 서버에 보낸다
    async function send(payload: SendPayload, userText?: string) {
        if (locked.current) return;
        if (!payload.message?.trim() && !payload.chip && !payload.answers) return;
        locked.current = true;
        setBusy(true);
        setError('');
        const shown = userText ?? payload.message?.trim();
        if (shown) setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'user', text: shown }]);
        const current = new AbortController();
        controller.current = current;
        const timeout = window.setTimeout(() => current.abort('timeout'), 30000);
        try {
            const response = await sendChat({ session_id: sessionId, ...payload }, current.signal);
            if (current.signal.aborted) return;
            setSessionId(response.session_id);
            setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'assistant', blocks: response.blocks }]);
        } catch (e) {
            if (current.signal.reason !== 'cancelled')
                setError(current.signal.aborted ? '응답 시간이 초과됐어요.' : e instanceof Error ? e.message : '응답 오류');
        } finally {
            clearTimeout(timeout);
            locked.current = false;
            setBusy(false);
            controller.current = null;
        }
    }

    function submit(value: string) {
        const text = value.trim();
        if (!text || locked.current) return;
        setInput('');
        void send({ message: text }, text);
    }

    const closeDetail = useCallback(() => { setDetail(null); setPurchasing(false); }, []);

    // 블록 컴포넌트(칩·조건 선택·상품 카드)가 쓰는 동작
    const actions: ChatActionsValue = useMemo(() => ({
        send: (payload, userText) => void send(payload, userText),
        openDetail: c => { setDetail(c); setPurchasing(false); },
        busy,
        sessionId,
    }), [busy, sessionId]);

    return (
        <ChatActions.Provider value={actions}>
        <div className="min-h-dvh bg-canvas text-ink">
            <header className="sticky top-0 z-10 border-b border-stone-200/70 bg-canvas/95 backdrop-blur">
                <div className="mx-auto flex h-[72px] max-w-6xl items-center justify-between px-5 sm:px-8">
                    <a href="./" className="flex items-center gap-2 text-lg font-semibold tracking-tight">
                        <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-ink text-white"><Sparkles size={17} /></span>
                        AI 식품 추천
                    </a>
                    <div className="flex items-center gap-3">
                        <span className="hidden rounded-full border border-stone-200 bg-white px-3 py-1 text-[11px] text-stone-500 md:inline">API 연결 준비 중</span>
                        <div className="hidden sm:flex">
                            <FlowStepper step={step} />
                        </div>
                        <button className="flex items-center gap-1 rounded-lg p-2 text-xs hover:bg-stone-100" disabled={busy} onClick={() => { setMessages([]); setSessionId(null); setError(''); setInput(''); closeDetail(); }}>
                            <Plus size={16} /><span className="hidden sm:inline">새 대화</span>
                        </button>
                    </div>
                </div>
            </header>

            <main className="mx-auto w-full max-w-[900px] px-4 pb-8 pt-8 sm:px-8">
                {!messages.length ? (
                    <section className="pb-12 pt-8 sm:pt-16">
                        <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-stone-200 bg-white px-4 py-2.5 text-sm text-accent">
                            <Sparkles size={18} />더 쉬운 선택의 시작
                        </div>
                        <h1 className="text-3xl font-medium leading-[1.35] tracking-tight sm:text-4xl">
                            식품 구매, <span className="text-accent">무엇이든 물어보세요!</span>
                        </h1>
                        <p className="mt-5 text-sm leading-7 text-stone-500 sm:text-base">
                            원하는 상품이나 만들고 싶은 요리를 말해 주세요.<br />중요한 조건을 확인하고, 비교하기 쉽게 정리해 드려요.
                        </p>
                        {/* 제휴 수수료 고지 — 첫 화면 첫 부분 (공정위 추천·보증 심사지침, 쿠팡 파트너스 정책) */}
                        <p className="mt-4 rounded-xl border border-stone-200 bg-white px-4 py-3 text-xs leading-6 text-stone-600">
                            <strong className="font-semibold text-ink">광고 · 제휴 링크 안내</strong>{' '}
                            이 사이트는 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다.
                            수수료는 본 사이트 운영과 무료 서비스 유지에 도움이 되며, 추천 순위에는 반영하지 않습니다.
                        </p>

                        {/* 예시 질문 버튼 렌더링 영역 (모바일 1열, PC 2x2 그리드) */}
                        <div className="mt-9 grid gap-3 grid-cols-1 sm:grid-cols-2">
                            {examples.map(({ icon: Icon, ...item }) => {
                                return (
                                    <button key={item.text} type="button" disabled={busy} onClick={() => submit(item.text)} className="group flex flex-col justify-between rounded-2xl border border-stone-200 bg-white p-5 text-left transition hover:-translate-y-1 hover:border-accent/40 hover:shadow-sm">
                                        <div>
                                            <div className="mb-4 flex items-center gap-2">
                                                <span className="flex h-9 w-9 items-center justify-center rounded-full bg-accent/10 text-accent">
                                                    <Icon size={20} />
                                                </span>
                                                <span className="rounded-full bg-stone-100 px-2.5 py-1 text-xs font-semibold text-stone-600">
                                                    {item.label}
                                                </span>
                                            </div>
                                            <p className="text-lg font-medium leading-relaxed text-ink break-keep">
                                                "{item.text}"
                                            </p>
                                        </div>
                                        <div className="mt-5 flex w-full items-center justify-between text-sm text-stone-400">
                                            <span>{item.note}</span>
                                            <ArrowRight size={16} className="transition group-hover:text-accent group-hover:translate-x-1" />
                                        </div>
                                    </button>
                                );
                            })}
                        </div>
                        {examplesDate && <p className="mt-3 text-right text-[11px] text-stone-400">예시 질문 기준일 {examplesDate} · 네이버 식품 키워드 순위</p>}
                        <p className="mt-7 text-center text-xs text-stone-400">조건 확인 → 후보 비교 → 근거 확인 → 판매처 연결</p>
                    </section>
                ) : (
                    <div className="space-y-8">
                        {messages.map(message => (
                            <section key={message.id} className={message.role === 'user' ? 'flex justify-end' : 'min-w-0'} aria-label={message.role === 'user' ? '내 질문' : 'AI 응답'}>
                                {message.role === 'user' ? (
                                    <p className="max-w-[88%] whitespace-pre-wrap break-words rounded-3xl rounded-tr-md bg-[#eaece5] px-5 py-3 text-sm leading-7">{message.text}</p>
                                ) : (
                                    <>
                                        <div className="mb-4 flex items-center gap-2 text-xs font-semibold"><Sparkles size={16} className="text-accent" />AI 식품 추천</div>
                                        <BlockRenderer blocks={message.blocks ?? []} />
                                    </>
                                )}
                            </section>
                        ))}
                        <div role="status" aria-live="polite">{busy && <p className="animate-pulse text-sm text-stone-500">조건을 살펴보고 있어요…</p>}</div>
                    </div>
                )}
                {error && <div role="alert" className="mt-4 rounded-xl bg-red-50 p-4 text-sm text-red-700">{error}</div>}
                <div ref={bottom} />
            </main>

            <footer className="sticky bottom-0 mx-auto w-full max-w-[900px] bg-gradient-to-t from-canvas via-canvas to-canvas/90 px-4 pb-[max(1rem,env(safe-area-inset-bottom))] pt-4 sm:px-8">
                <form onSubmit={e => { e.preventDefault(); submit(input); }} className="rounded-3xl border border-stone-200 bg-white p-3 shadow-[0_4px_24px_#00000006]">
                    <label htmlFor="prompt" className="sr-only">쇼핑 질문</label>
                    <textarea id="prompt" value={input} onChange={e => setInput(e.target.value)} rows={2} maxLength={4000} placeholder="어떤 상품을 찾으세요? 예산과 원하는 조건을 알려주세요." className="max-h-40 min-h-14 w-full resize-y bg-transparent px-2 py-1 text-sm leading-6 outline-none placeholder:text-stone-400" onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit(input); } }} />
                    <div className="flex items-center justify-between px-1">
                        <span className="text-[11px] text-stone-400">추천 정보는 판매처에서 최종 확인해 주세요</span>
                        {busy ? (
                            <button type="button" aria-label="응답 중단" className="send" onClick={() => controller.current?.abort('cancelled')}><Square size={15} /></button>
                        ) : (
                            <button type="submit" className="send" aria-label="질문 보내기" disabled={!input.trim()}><ArrowUp size={18} /></button>
                        )}
                    </div>
                </form>
                <p className="mt-3 text-center text-[10px] text-stone-400">쿠팡 파트너스 활동의 일환으로 일정액의 수수료를 제공받으며, 수수료는 본 사이트 운영에 도움이 됩니다. 가격·배송·리뷰는 확인 시점에 따라 달라질 수 있어요.</p>
            </footer>

            {detail && <ProductDetail key={detail.key} c={detail} sessionId={sessionId} purchasing={purchasing} onPurchasing={setPurchasing} onClose={closeDetail} />}
        </div>
        </ChatActions.Provider>
    );
}
