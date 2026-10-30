import { defineTool } from 'eve/tools';
import { z } from 'zod';
import { gateway } from '../../gateway.mjs';

export default defineTool({
  description: 'Fetch the delivered Markdown report of an order (read-only).',
  inputSchema: z.object({ order_id: z.string().regex(/^[0-9a-f]{32}$/) }),
  async execute({ order_id }) {
    const o = await gateway(`/internal/orders/${order_id}`, { internal: true });
    return { state: o.state, service: o.service, country: o.country, markdown: o.markdown ?? null };
  },
});
