// payments: el servicio de cobros de juguete (Express + Prisma, TypeScript).
import express from "express";
import { PrismaClient } from "@prisma/client";

const prisma = new PrismaClient();
const app = express();
app.use(express.json());

app.post("/charges", async (req, res) => {
  const charge = await prisma.charge.create({ data: { order: req.body.order, amount: req.body.amount } });
  res.json(charge);
});

app.get("/charges/:id", async (req, res) => {
  res.json(await prisma.charge.findUnique({ where: { id: Number(req.params.id) } }));
});

app.listen(3000);
