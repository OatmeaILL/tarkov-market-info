package com.tarkov.marketinfo.data

import com.tarkov.marketinfo.core.PricePoint
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 曲线缓存的序列化往返。
 *
 * 这两个函数手写而不用 org.json 就是为了能在这里跑测试
 * （org.json 在纯 JVM 下是 stub，会抛 "not mocked"）。
 */
class CurveCodecTest {

    @Test
    fun `点位往返不变`() {
        val points = listOf(
            PricePoint(1_700_000_000L, 61328),
            PricePoint(1_700_003_600L, 62100),
            PricePoint(1_700_007_200L, 59800),
        )
        assertEquals(points, decodePoints(encodePoints(points)))
    }

    @Test
    fun `空列表往返`() {
        assertEquals("[]", encodePoints(emptyList()))
        assertEquals(emptyList<PricePoint>(), decodePoints("[]"))
    }

    @Test
    fun `单个点`() {
        val one = listOf(PricePoint(1_700_000_000L, 100))
        assertEquals(one, decodePoints(encodePoints(one)))
    }

    @Test
    fun `坏数据当空不抛`() {
        // 缓存被写坏时不能让界面崩，退化成"没有曲线"
        assertEquals(emptyList<PricePoint>(), decodePoints(""))
        assertEquals(emptyList<PricePoint>(), decodePoints("坏数据"))
        assertEquals(emptyList<PricePoint>(), decodePoints("[[]]"))
        assertEquals(emptyList<PricePoint>(), decodePoints("[[abc,def]]"))
    }

    @Test
    fun `丢弃价格非正的点`() {
        // 价格为 0 的点画在曲线上会把线拽到 0，得剔掉
        val decoded = decodePoints("[[100,50],[200,0],[300,80]]")
        assertEquals(2, decoded.size)
        assertTrue(decoded.all { it.price > 0 })
    }

    @Test
    fun `多余逗号不影响解析`() {
        val decoded = decodePoints("[[100,50],,[[200,60]]")
        assertTrue("至少应解出 1 个点，实际 ${decoded.size}", decoded.isNotEmpty())
    }
}
