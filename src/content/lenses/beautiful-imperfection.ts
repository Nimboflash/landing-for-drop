import rawLens from "./beautiful-imperfection.mock.json";
import { weeklyLensSchema } from "../drop-weekly-lens.schema";

export const beautifulImperfectionLens = weeklyLensSchema.parse(rawLens);

export default beautifulImperfectionLens;
