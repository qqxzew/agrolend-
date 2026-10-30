import { defineTool } from 'eve/tools';
import { z } from 'zod';
import { gateway } from '../../gateway.mjs';

export default defineTool({
  description: 'Dry-run: check whether an input is valid for a service and country, and get the price. Creates, computes and charges nothing.',
  inputSchema: z.object({ service: z.enum(['land_audit', 'lease_check']), country: z.enum(['DE', 'IN']), input: z.record(z.string(), z.any()) }),
  async execute(args) {
    return gateway('/internal/validate', { method: 'POST', body: args, internal: true });
  },
});
