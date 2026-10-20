import { z } from 'zod';

export const chipSchema = z.object({ label: z.string(), value: z.string() });

export const productSchema = z.object({
    rank: z.number(),
    title: z.string(),
    price: z.number().nonnegative().optional(),
    total: z.number().nonnegative().optional(),
    mall: z.string(),
    image_url: z.string().optional(),
    reasoning: z.string(),
    follow_up: z.array(chipSchema).default([]),
    weight: z.string().optional(),
    delivery: z.string().optional(),
    option: z.string().optional(),
    quantity: z.number().int().positive().optional(),
    product_url: z.string().optional(),
    seller_claims: z.array(z.string()).default([]),
    review_summary: z.string().optional(),
    sources: z.array(z.object({ label: z.string(), url: z.string() })).default([]),
    unknowns: z.array(z.string()).default([])
});

const knownSchemas = {
    text: z.object({ text: z.string() }),
    comparison_pair: z.object({
        pairs: z.array(z.object({
            pair_index: z.number(),
            cards: z.array(productSchema).min(1).max(2),
            chips: z.array(chipSchema).default([])
        }))
    }),
    clarify_form: z.object({ title: z.string(), options: z.array(chipSchema) }),
    shipping_options: z.object({
        is_overseas: z.boolean(),
        estimated_days: z.string(),
        total_landed_cost: z.number().nonnegative(),
        agency: z.string(),
        is_final: z.boolean().optional()
    }),
    chips: z.object({ items: z.array(z.string()), mode: z.string().optional() }),
    recipe: z.object({ title: z.string(), ingredients: z.array(z.object({ name: z.string(), amount: z.string(), required: z.boolean() })) }),
    sponsored: z.object({ title: z.string(), text: z.string() })
};

export type KnownBlock = { [K in keyof typeof knownSchemas]: { type: K; data: z.infer<(typeof knownSchemas)[K]> } }[keyof typeof knownSchemas];
export type Block = KnownBlock | { type: 'unsupported'; data: { originalType: string } };
export type Product = z.infer<typeof productSchema>;
export type Chip = z.infer<typeof chipSchema>;

export interface ChatResponse { session_id: string; blocks: Block[] }
export interface Message { id: string; role: 'user' | 'assistant'; text?: string; blocks?: Block[] }

// 에러가 났던 parseResponse 함수 복원
export function parseResponse(input: unknown): ChatResponse {
    const envelope = z.object({
        session_id: z.string(),
        blocks: z.array(z.object({ type: z.string(), data: z.unknown() }))
    }).parse(input);

    return {
        ...envelope,
        blocks: envelope.blocks.map(block => {
            if (!(block.type in knownSchemas)) {
                return { type: 'unsupported', data: { originalType: block.type } };
            }
            const key = block.type as keyof typeof knownSchemas;
            return { type: key, data: knownSchemas[key].parse(block.data) } as KnownBlock;
        })
    };
}