// Qué logos mostrar en cada nodo del diagrama: la tecnología del componente (Postgres, Redis, FastAPI…) y
// dónde corre (AWS, Supabase, Docker…). Sale de lo que ya trae el modelo: el motor y el proveedor de cada
// componente, el framework del repo y los Dockerfile o compose que encontró la ingesta. Lo que no calza
// no lleva logo: no se adivina.
import type { TechIconName } from "@/components/editor/tech-icons";
import type { ArchitectureModel, GraphNode } from "./editor-api";

export interface TechBadge {
  icon: TechIconName;
  label: string;
}

export interface NodeTech {
  /** La tecnología del componente: reemplaza al ícono genérico del tipo. */
  main?: TechBadge;
  /** Dónde corre, de más a menos específico. */
  platforms: TechBadge[];
}

// El orden importa: gana el primero que calza (por ejemplo, «aws s3» antes que «aws»).
const TECHNOLOGIES: [RegExp, TechIconName, string][] = [
  [/postgres/, "postgresql", "PostgreSQL"],
  [/mysql|mariadb/, "mysql-icon", "MySQL"],
  [/mongo/, "mongodb-icon", "MongoDB"],
  [/valkey/, "valkey", "Valkey"],
  [/redis/, "redis", "Redis"],
  [/rabbit/, "rabbitmq-icon", "RabbitMQ"],
  [/kafka/, "kafka-icon", "Kafka"],
  [/nginx/, "nginx", "nginx"],
  [/elastic|opensearch/, "elasticsearch", "Elasticsearch"],
  [/dynamo/, "aws-dynamodb", "DynamoDB"],
  [/\bsqs\b/, "aws-sqs", "Amazon SQS"],
  [/\bsns\b/, "aws-sns", "Amazon SNS"],
  [/\bs3\b/, "aws-s3", "Amazon S3"],
  [/lambda/, "aws-lambda", "AWS Lambda"],
  [/supabase/, "supabase-icon", "Supabase"],
  [/firebase|firestore/, "firebase", "Firebase"],
  [/stripe/, "stripe", "Stripe"],
  [/sendgrid/, "sendgrid-icon", "SendGrid"],
  [/mailgun/, "mailgun-icon", "Mailgun"],
  [/twilio/, "twilio-icon", "Twilio"],
  [/openai|\bgpt/, "openai-icon", "OpenAI"],
  [/anthropic|claude/, "anthropic-icon", "Anthropic"],
  [/sentry/, "sentry-icon", "Sentry"],
  [/auth0/, "auth0-icon", "Auth0"],
  [/cloudflare/, "cloudflare-icon", "Cloudflare"],
  [/github/, "github-icon", "GitHub"],
];

const FRAMEWORKS: [RegExp, TechIconName, string][] = [
  [/fastapi/, "fastapi-icon", "FastAPI"],
  [/django/, "django-icon", "Django"],
  [/express/, "express", "Express"],
  [/nest/, "nestjs", "NestJS"],
  [/next/, "nextjs-icon", "Next.js"],
  [/rails/, "rails", "Ruby on Rails"],
  [/spring/, "spring-icon", "Spring"],
  [/laravel/, "laravel", "Laravel"],
  [/node|koa|hono/, "nodejs-icon", "Node.js"],
  [/flask|python/, "python", "Python"],
  [/\bgo\b|gin|fiber|echo/, "go", "Go"],
];

const PLATFORMS: [RegExp, TechIconName, string][] = [
  [/supabase/, "supabase-icon", "Supabase"],
  [
    /fargate|\becs\b|\bec2\b|lambda|\brds|aurora|elasticache|dynamo|\baws\b/,
    "aws",
    "AWS",
  ],
  [
    /cloud_run|cloud_sql|\bgke\b|\bgcp\b|google/,
    "google-cloud",
    "Google Cloud",
  ],
  [/azure|app_service|\baks\b/, "microsoft-azure", "Azure"],
  [/kubernetes|\bk8s\b/, "kubernetes", "Kubernetes"],
  [/railway/, "railway", "Railway"],
  [/heroku/, "heroku-icon", "Heroku"],
  [/vercel/, "vercel-icon", "Vercel"],
  [/firebase/, "firebase", "Firebase"],
  [/docker/, "docker-icon", "Docker"],
];

function match(
  text: string,
  table: [RegExp, TechIconName, string][],
): TechBadge | undefined {
  const found = table.find(([pattern]) => pattern.test(text));
  return found ? { icon: found[1], label: found[2] } : undefined;
}

type ModelExtras = {
  deployment?: { iac?: { files?: { kind?: string }[] } };
  repo?: { source?: { framework?: string | null } };
};

/** Si el repo trae Dockerfile o compose: la API corre en contenedores. */
function usesDocker(model: ArchitectureModel | undefined) {
  const files = (model as ModelExtras | undefined)?.deployment?.iac?.files;
  return !!files?.some(
    (file) => file.kind === "dockerfile" || file.kind === "compose",
  );
}

export function nodeTech(node: GraphNode, model?: ArchitectureModel): NodeTech {
  const details = node.details as GraphNode["details"] & {
    provider?: string | null;
  };
  const technology = (details.technology ?? "").toLowerCase();
  const provider = (details.provider ?? "").toLowerCase();
  const label = node.label.toLowerCase();

  let main: TechBadge | undefined;
  if (node.kind === "api") {
    const framework =
      (model as ModelExtras | undefined)?.repo?.source?.framework ?? "";
    main = match(framework.toLowerCase(), FRAMEWORKS);
  } else if (node.kind === "service") {
    main = match(technology, FRAMEWORKS) ?? match(technology, TECHNOLOGIES);
  } else {
    // el motor declarado manda; si no hay, el proveedor (rds_postgres) o el nombre del componente
    main =
      match(technology, TECHNOLOGIES) ??
      match(provider, TECHNOLOGIES) ??
      match(label, TECHNOLOGIES);
  }

  const platforms: TechBadge[] = [];
  const platform = match(provider, PLATFORMS);
  if (platform) platforms.push(platform);
  if (node.kind === "api" && usesDocker(model))
    platforms.push({ icon: "docker-icon", label: "Docker" });

  return {
    main,
    platforms: platforms
      .filter(
        (item, index) =>
          item.icon !== main?.icon &&
          platforms.findIndex((other) => other.icon === item.icon) === index,
      )
      .slice(0, 2),
  };
}
