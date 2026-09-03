import fs from "node:fs/promises";
import path from "node:path";

import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";


function parseArgs(argv) {
  const args = {};
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith("--")) continue;
    const key = token.slice(2);
    args[key] = argv[index + 1] && !argv[index + 1].startsWith("--")
      ? argv[++index]
      : true;
  }
  return args;
}


async function walkJsonFiles(root) {
  const files = [];
  async function visit(directory) {
    const entries = await fs.readdir(directory, { withFileTypes: true });
    for (const entry of entries) {
      const entryPath = path.join(directory, entry.name);
      if (entry.isDirectory()) {
        await visit(entryPath);
      } else if (entry.isFile() && entry.name.endsWith(".json")) {
        files.push(entryPath);
      }
    }
  }
  await visit(root);
  return files.sort();
}


async function readCollection(inputDir) {
  const files = await walkJsonFiles(inputDir);
  let index = { items: [] };
  const records = [];
  const responseRows = [];

  for (const file of files) {
    const payload = JSON.parse(await fs.readFile(file, "utf8"));
    if (path.basename(file) === "index.json") {
      index = payload;
      continue;
    }
    if (path.basename(file).endsWith(".error.json")) continue;

    for (const row of payload.room_rows || []) {
      records.push({
        ...row,
        "JSON文件": path.relative(inputDir, file),
      });
    }
    for (const response of payload.responses || []) {
      responseRows.push({
        "酒店名称": payload.hotel_name || "",
        "入住日期": payload.check_in || "",
        "离店日期": payload.check_out || "",
        "接口状态": response.status ?? null,
        "请求方法": response.method || "",
        "接口URL": response.url || "",
        "JSON文件": path.relative(inputDir, file),
        "响应JSON字符数": JSON.stringify(response.data || {}).length,
      });
    }
  }

  return { index, records, responseRows };
}


function excelDate(value) {
  if (!value) return null;
  const match = String(value).match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return null;
  return new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
}


function cellValue(value, key) {
  if (key === "入住日期" || key === "离店日期") return excelDate(value);
  if (value === undefined) return null;
  if (value !== null && typeof value === "object") return JSON.stringify(value);
  return value;
}


function columnName(index) {
  let number = index + 1;
  let result = "";
  while (number > 0) {
    const remainder = (number - 1) % 26;
    result = String.fromCharCode(65 + remainder) + result;
    number = Math.floor((number - 1) / 26);
  }
  return result;
}


function applySheetStyle(sheet, headers, dataRows, tableName, widths) {
  const values = [headers, ...dataRows];
  const fullRange = sheet.getRangeByIndexes(0, 0, values.length, headers.length);
  fullRange.values = values;
  fullRange.format.wrapText = false;

  const headerRange = sheet.getRangeByIndexes(0, 0, 1, headers.length);
  headerRange.format = {
    fill: "#1F4E78",
    font: { bold: true, color: "#FFFFFF" },
    wrapText: true,
  };
  headerRange.format.rowHeight = 30;
  sheet.showGridLines = false;
  sheet.freezePanes.freezeRows(1);

  const tableRange = `A1:${columnName(headers.length - 1)}${values.length}`;
  const table = sheet.tables.add(tableRange, true, tableName);
  table.style = "TableStyleMedium2";
  table.showFilterButton = true;

  widths.forEach((width, index) => {
    sheet.getRangeByIndexes(0, index, values.length, 1).format.columnWidth = width;
  });
}


function writeDateAndNumberFormats(sheet, headers, dataRowCount) {
  if (!dataRowCount) return;
  const dateColumns = headers
    .map((header, index) => ({ header, index }))
    .filter(({ header }) => header === "入住日期" || header === "离店日期");
  for (const { index } of dateColumns) {
    sheet.getRangeByIndexes(1, index, dataRowCount, 1).format.numberFormat = "yyyy-mm-dd";
  }

  for (const header of ["价格", "原价"]) {
    const index = headers.indexOf(header);
    if (index >= 0) {
      sheet.getRangeByIndexes(1, index, dataRowCount, 1).format.numberFormat = "#,##0.00";
    }
  }
  for (const header of ["余房", "销售方案ID", "接口状态", "响应JSON字符数"]) {
    const index = headers.indexOf(header);
    if (index >= 0) {
      sheet.getRangeByIndexes(1, index, dataRowCount, 1).format.numberFormat = "#,##0";
    }
  }
}


function wrapColumns(sheet, headers, dataRowCount, columnNames, rowHeight = 34) {
  if (!dataRowCount) return;
  for (const columnNameValue of columnNames) {
    const index = headers.indexOf(columnNameValue);
    if (index >= 0) {
      sheet.getRangeByIndexes(1, index, dataRowCount, 1).format.wrapText = true;
    }
  }
  sheet.getRangeByIndexes(1, 0, dataRowCount, headers.length).format.rowHeight = rowHeight;
}


async function renderSheets(workbook, outputPath, sheetNames) {
  const outputDir = path.dirname(outputPath);
  const baseName = path.basename(outputPath, path.extname(outputPath));
  for (const sheetName of sheetNames) {
    const preview = await workbook.render({
      sheetName,
      autoCrop: "all",
      scale: 1,
      format: "png",
    });
    const previewPath = path.join(outputDir, `${baseName}.${sheetName}.png`);
    await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));
    console.log(`预览文件：${previewPath}`);
  }
}


async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (!args["input-dir"] || !args.output) {
    throw new Error("用法：node ctrip_hotel_excel_builder.mjs --input-dir <目录> --output <文件> [--preview]");
  }

  const inputDir = path.resolve(args["input-dir"]);
  const outputPath = path.resolve(args.output);
  const { index, records, responseRows } = await readCollection(inputDir);

  const priceHeaders = [
    "酒店名称", "入住日期", "离店日期", "房型", "房型ID", "销售方案", "销售方案ID",
    "价格", "原价", "货币", "显示价格", "总价展示", "床型", "早餐及权益", "取消政策",
    "预订状态", "可预订", "余房", "销售方案Key", "接口状态", "接口URL", "JSON文件", "采集时间", "详情页URL",
  ];
  const priceRows = records.map((record) => priceHeaders.map((header) => cellValue(record[header], header)));

  const summaryHeaders = ["酒店名称", "入住日期", "离店日期", "状态", "接口响应数", "房型行数", "详情页URL", "JSON文件", "错误"];
  const summaryRows = (index.items || []).map((item) => summaryHeaders.map((header) => {
    const sourceKey = {
      "酒店名称": "hotel_name",
      "入住日期": "check_in",
      "离店日期": "check_out",
      "状态": "status",
      "接口响应数": "response_count",
      "房型行数": "room_row_count",
      "详情页URL": "detail_url",
      "JSON文件": "file",
      "错误": "error",
    }[header];
    const value = item[sourceKey];
    return header === "JSON文件" && value
      ? path.relative(inputDir, value)
      : cellValue(value, header);
  }));

  const responseHeaders = ["酒店名称", "入住日期", "离店日期", "接口状态", "请求方法", "接口URL", "JSON文件", "响应JSON字符数"];
  const responseValues = responseRows.map((record) => responseHeaders.map((header) => cellValue(record[header], header)));

  const workbook = Workbook.create();
  const priceSheet = workbook.worksheets.add("房型价格");
  const summarySheet = workbook.worksheets.add("采集汇总");
  const responseSheet = workbook.worksheets.add("接口概览");
  const noteSheet = workbook.worksheets.add("说明");

  applySheetStyle(
    priceSheet,
    priceHeaders,
    priceRows,
    "RoomPriceTable",
    [24, 12, 12, 24, 14, 20, 14, 12, 12, 10, 14, 14, 20, 28, 28, 12, 10, 10, 24, 12, 38, 48, 24, 52],
  );
  writeDateAndNumberFormats(priceSheet, priceHeaders, priceRows.length);
  wrapColumns(priceSheet, priceHeaders, priceRows.length, [
    "早餐及权益", "取消政策", "接口URL", "JSON文件", "详情页URL",
  ]);

  applySheetStyle(
    summarySheet,
    summaryHeaders,
    summaryRows,
    "CollectionSummaryTable",
    [24, 12, 12, 12, 14, 12, 52, 52, 28],
  );
  writeDateAndNumberFormats(summarySheet, summaryHeaders, summaryRows.length);
  wrapColumns(summarySheet, summaryHeaders, summaryRows.length, ["详情页URL", "JSON文件", "错误"]);

  applySheetStyle(
    responseSheet,
    responseHeaders,
    responseValues,
    "ResponseOverviewTable",
    [24, 12, 12, 12, 12, 52, 52, 18],
  );
  writeDateAndNumberFormats(responseSheet, responseHeaders, responseValues.length);
  wrapColumns(responseSheet, responseHeaders, responseValues.length, ["接口URL", "JSON文件"]);

  const noteRows = [
    ["生成时间", new Date()],
    ["原始 JSON 目录", inputDir],
    ["数据说明", "房型价格来自 getHotelRoomListInland 接口响应；完整响应仍按酒店和日期保存在 JSON 文件中。"],
    ["价格口径", "价格列为接口 priceInfo.price；原价列为接口 deletePricewithOutCurrency。"],
    ["登录状态", "采集器只在检测到“我的订单”且登录入口消失后继续。"],
  ];
  applySheetStyle(noteSheet, ["项目", "内容"], noteRows, "WorkbookNotesTable", [22, 90]);
  noteSheet.getRangeByIndexes(1, 1, 1, 1).format.numberFormat = "yyyy-mm-dd hh:mm";
  noteSheet.getRangeByIndexes(1, 1, noteRows.length, 1).format.wrapText = true;
  noteSheet.getRangeByIndexes(1, 1, noteRows.length, 1).format.rowHeight = 30;

  const check = await workbook.inspect({
    kind: "table",
    sheetId: "房型价格",
    range: "A1:X8",
    include: "values,formulas",
    tableMaxRows: 8,
    tableMaxCols: 24,
    tableMaxCellChars: 80,
  });
  console.log(check.ndjson);
  const errors = await workbook.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
    options: { useRegex: true, maxResults: 50 },
    summary: "final formula error scan",
  });
  console.log(errors.ndjson);

  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  if (args.preview) {
    await renderSheets(workbook, outputPath, ["房型价格", "采集汇总", "接口概览", "说明"]);
  }
  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(outputPath);
  console.log(`Excel 已生成：${outputPath}`);
  console.log(`房型明细行：${priceRows.length}；采集记录：${summaryRows.length}；接口响应：${responseValues.length}`);
}


main().catch((error) => {
  console.error(error?.stack || error);
  process.exitCode = 1;
});
