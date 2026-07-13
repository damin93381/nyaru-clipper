import { readFileSync } from "node:fs";
import { inflateSync } from "node:zlib";

const PNG_SIGNATURE_LENGTH = 8;
const BYTES_PER_RGB_PIXEL = 3;
const NEAR_BLACK_CHANNEL_MAX = 48;
const MIN_SUSPICIOUS_REGION_PIXELS = 4_096;

function readPng(path) {
  const buffer = readFileSync(path);
  if (buffer.subarray(0, PNG_SIGNATURE_LENGTH).toString("hex") !== "89504e470d0a1a0a") {
    throw new Error(`${path} is not a PNG file.`);
  }

  let offset = PNG_SIGNATURE_LENGTH;
  let width = 0;
  let height = 0;
  let bitDepth = 0;
  let colorType = 0;
  const idat = [];
  while (offset < buffer.length) {
    const length = buffer.readUInt32BE(offset);
    const type = buffer.subarray(offset + 4, offset + 8).toString("ascii");
    const chunk = buffer.subarray(offset + 8, offset + 8 + length);
    offset += length + 12;
    if (type === "IHDR") {
      width = chunk.readUInt32BE(0);
      height = chunk.readUInt32BE(4);
      bitDepth = chunk[8];
      colorType = chunk[9];
    }
    if (type === "IDAT") idat.push(chunk);
    if (type === "IEND") break;
  }
  if (bitDepth !== 8 || colorType !== 2) {
    throw new Error(`${path} must be an 8-bit RGB PNG; received bit depth ${bitDepth} and color type ${colorType}.`);
  }
  return { data: inflateSync(Buffer.concat(idat)), height, path, width };
}

function paeth(left, above, upperLeft) {
  const estimate = left + above - upperLeft;
  const leftDistance = Math.abs(estimate - left);
  const aboveDistance = Math.abs(estimate - above);
  const upperLeftDistance = Math.abs(estimate - upperLeft);
  if (leftDistance <= aboveDistance && leftDistance <= upperLeftDistance) return left;
  return aboveDistance <= upperLeftDistance ? above : upperLeft;
}

function decodeRgb({ data, height, path, width }) {
  const stride = width * BYTES_PER_RGB_PIXEL;
  const pixels = Buffer.alloc(stride * height);
  let source = 0;
  for (let y = 0; y < height; y += 1) {
    const filter = data[source++];
    for (let x = 0; x < stride; x += 1) {
      const raw = data[source++];
      const left = x >= BYTES_PER_RGB_PIXEL ? pixels[y * stride + x - BYTES_PER_RGB_PIXEL] : 0;
      const above = y > 0 ? pixels[(y - 1) * stride + x] : 0;
      const upperLeft = y > 0 && x >= BYTES_PER_RGB_PIXEL ? pixels[(y - 1) * stride + x - BYTES_PER_RGB_PIXEL] : 0;
      const value = filter === 0 ? raw : filter === 1 ? (raw + left) & 255 : filter === 2 ? (raw + above) & 255 : filter === 3 ? (raw + Math.floor((left + above) / 2)) & 255 : filter === 4 ? (raw + paeth(left, above, upperLeft)) & 255 : Number.NaN;
      if (!Number.isFinite(value)) throw new Error(`${path} uses unsupported PNG filter ${filter}.`);
      pixels[y * stride + x] = value;
    }
  }
  return pixels;
}

function findSuspiciousRegions(pixels, width, height) {
  const dark = new Uint8Array(width * height);
  for (let pixel = 0; pixel < dark.length; pixel += 1) {
    const offset = pixel * BYTES_PER_RGB_PIXEL;
    dark[pixel] = pixels[offset] <= NEAR_BLACK_CHANNEL_MAX && pixels[offset + 1] <= NEAR_BLACK_CHANNEL_MAX && pixels[offset + 2] <= NEAR_BLACK_CHANNEL_MAX ? 1 : 0;
  }
  const regions = [];
  const queue = new Int32Array(dark.length);
  for (let start = 0; start < dark.length; start += 1) {
    if (dark[start] === 0) continue;
    let head = 0;
    let tail = 0;
    let minX = start % width;
    let maxX = minX;
    let minY = Math.floor(start / width);
    let maxY = minY;
    dark[start] = 0;
    queue[tail++] = start;
    while (head < tail) {
      const pixel = queue[head++];
      const x = pixel % width;
      const y = Math.floor(pixel / width);
      minX = Math.min(minX, x); maxX = Math.max(maxX, x); minY = Math.min(minY, y); maxY = Math.max(maxY, y);
      for (const neighbor of [pixel - 1, pixel + 1, pixel - width, pixel + width]) {
        const neighborX = neighbor % width;
        if (neighbor < 0 || neighbor >= dark.length || (Math.abs(neighborX - x) > 1 && (neighbor === pixel - 1 || neighbor === pixel + 1)) || dark[neighbor] === 0) continue;
        dark[neighbor] = 0;
        queue[tail++] = neighbor;
      }
    }
    if (tail >= MIN_SUSPICIOUS_REGION_PIXELS) regions.push({ height: maxY - minY + 1, pixels: tail, width: maxX - minX + 1, x: minX, y: minY });
  }
  return regions;
}

function parseAllowedDarkRegions(args) {
  return args
    .filter((arg) => arg.startsWith("--allow-dark-region="))
    .map((arg) => arg.slice("--allow-dark-region=".length).split(",").map(Number))
    .map(([x, y, width, height]) => ({ height, width, x, y }));
}

function isAllowed(region, allowedRegions) {
  return allowedRegions.some((allowed) => region.x >= allowed.x && region.y >= allowed.y && region.x + region.width <= allowed.x + allowed.width && region.y + region.height <= allowed.y + allowed.height);
}

const args = process.argv.slice(2);
const allowedDarkRegions = parseAllowedDarkRegions(args);
const paths = args.filter((arg) => !arg.startsWith("--allow-dark-region="));
if (paths.length === 0) throw new Error("Usage: pnpm visual:check-png [--allow-dark-region=x,y,width,height] <screenshot.png> [...screenshots.png]");
const results = paths.map((path) => {
  const image = readPng(path);
  const regions = findSuspiciousRegions(decodeRgb(image), image.width, image.height);
  const rejectedRegions = regions.filter((region) => !isAllowed(region, allowedDarkRegions));
  return { allowedDarkRegions, path, regions, verdict: rejectedRegions.length === 0 ? "accept" : "reject" };
});
console.log(JSON.stringify({ results }, null, 2));
if (results.some((result) => result.verdict === "reject")) process.exitCode = 1;
