import { defineTool } from 'eve/tools';
import { z } from 'zod';
import { gateway } from '../../gateway.mjs';

export default defineTool({
  description: 'Services, prices, countries and coverage notes of AgroLand. Prices here are the only valid prices.',
  inputSchema: z.object({}),
  async execute() {
    const c = await gateway('/api/config');
    return { network: c.network, token: c.token, services: Object.fromEntries(Object.entries(c.services).map(([k, v]: any) => [k, { title: v.title, price: v.price.display, countries: v.countries, summary: v.summary }])), coverage: c.coverage };
  },
});
