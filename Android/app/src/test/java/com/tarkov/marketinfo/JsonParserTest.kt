package com.tarkov.marketinfo.data

import com.tarkov.marketinfo.data.SyncService.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 手写 JSON 解析器的行为验证。
 *
 * 这个解析器要同时满足两个约束，所以值得单独测：
 * 1. 不用 org.json —— 它在纯 JVM 单元测试里是 stub，会抛 "not mocked"
 * 2. 坏数据不能抛 —— 同步时一条脏数据不该让整次同步失败
 *
 * 写这个文件时踩过一个坑，记在这里免得下次再踩：
 * Kotlin 的**三引号字符串不能包含引号结尾的片段**。
 * 比如想表达「值以引号结尾」的期望串，写成三引号版本会多出一个引号、
 * 并把后面的代码吞进字符串里，报错却指向很远的行号（"Function declaration
 * must have a name"），非常难查。所以这里**一律用转义字符串**。
 */
class JsonParserTest {

    @Suppress("UNCHECKED_CAST")
    private fun obj(text: String): Map<String, Any?> = Json.parse(text) as Map<String, Any?>

    @Test
    fun parsesNestedObject() {
        val root = obj("{\"a\": {\"b\": {\"c\": 1}}, \"d\": \"x\"}")
        @Suppress("UNCHECKED_CAST")
        val a = root["a"] as Map<String, Any?>
        @Suppress("UNCHECKED_CAST")
        val b = a["b"] as Map<String, Any?>
        assertEquals(1L, b["c"])
        assertEquals("x", root["d"])
    }

    @Test
    fun parsesArray() {
        assertEquals(listOf(1L, 2L, 3L), Json.parse("[1,2,3]"))
        assertEquals(listOf("a", "b"), Json.parse("[\"a\",\"b\"]"))
    }

    @Test
    fun parsesFloatsAndNegatives() {
        assertEquals(3.5, Json.parse("3.5"))
        assertEquals(-2.5, Json.parse("-2.5"))
        // 科学计数法：接口偶尔会用
        assertEquals(1500.0, Json.parse("1.5e3"))
    }

    @Test
    fun parsesBooleanAndNull() {
        assertEquals(true, Json.parse("true"))
        assertEquals(false, Json.parse("false"))
        assertNull(Json.parse("null"))
    }

    @Test
    fun escapedQuotesInString() {
        // 真实库里就有这种名字：VOMZ P1X42 "WEAVER"
        val root = obj("{\"name\": \"VOMZ P1X42 \\\"WEAVER\\\"\"}")
        // 期望值以引号结尾，用字符字面量拼出来最清楚
        val expected = "VOMZ P1X42 " + '"' + "WEAVER" + '"'
        assertEquals(expected, root["name"])
    }

    @Test
    fun newlineAndBackslashInString() {
        val root = obj("{\"a\": \"x\\ny\", \"b\": \"c\\\\d\"}")
        assertEquals("x\ny", root["a"])
        assertEquals("c\\d", root["b"])
    }

    @Test
    fun chineseNotEscaped() {
        // 物品名全是中文，编码错了全变乱码
        val root = obj("{\"name\": \"SureFire SOCOM556-MONSTER 5.56x45 消音器\"}")
        assertEquals("SureFire SOCOM556-MONSTER 5.56x45 消音器", root["name"])
    }

    @Test
    fun emptyObjectAndArray() {
        assertEquals(0, obj("{}").size)
        assertEquals(0, (Json.parse("[]") as List<*>).size)
    }

    @Test
    fun whitespaceTolerated() {
        val root = obj("  {  \"a\" : 1 , \"b\" : [ 1 , 2 ]  }  ")
        assertEquals(1L, root["a"])
        assertEquals(listOf(1L, 2L), root["b"])
    }

    @Test
    fun badDataReturnsNull() {
        // 同步时接口返回脏数据，整个流程要能继续
        assertNull(Json.parse(""))
        assertNull(Json.parse("{"))
        assertNull(Json.parse("不是JSON"))
        assertNull(Json.parse("{\"a\": }"))
    }

    @Test
    fun truncatedJsonDoesNotThrow() {
        // 解析到一半断了：返回能解出的部分或 null，都不能抛
        assertNotNull(Json.parse("{\"a\": 1, \"b\": 2"))
    }

    @Test
    fun encodeStringEscapes() {
        assertEquals("\"x\"", Json.encodeString("x"))
        assertEquals("\"a\\\"b\"", Json.encodeString("a\"b"))
        assertEquals("\"a\\\\b\"", Json.encodeString("a\\b"))
        assertEquals("\"a\\nb\"", Json.encodeString("a\nb"))
    }

    @Test
    fun encodeControlChars() {
        // 不转义的话拼出来的 JSON 不合法，下游解析会挂
        val encoded = Json.encodeString("a\u0001b")
        assertTrue("应含 \\u 转义，实际=$encoded", encoded.contains("\\u0001"))
    }

    @Test
    fun encodeChinese() {
        assertEquals("\"消音器\"", Json.encodeString("消音器"))
    }

    @Test
    fun encodeDecodeRoundTrip() {
        val original = "SureFire SOCOM556 \"MONSTER\" \\ 消音器"
        val text = "{\"name\": " + Json.encodeString(original) + "}"
        assertEquals(original, obj(text)["name"])
    }

    @Test
    fun bigNumberKeepsPrecision() {
        // 价格偶尔是 8 位数，别被截成浮点
        val root = obj("{\"price\": 12345678}")
        assertEquals(12345678L, root["price"])
    }
}
