package dev.dualtheater.tv;

import org.junit.Test;
import static org.junit.Assert.*;

public class ConnectionTest {
    private static final String ID = "12345678-1234-4567-89ab-123456789abc";
    @Test public void sixDigitCodePreservesLeadingZero() {
        assertEquals("012345", ConnectionCode.normalize("012345"));
        assertEquals("012345", ConnectionCode.normalize("012-345"));
        assertEquals("012345", ConnectionCode.normalize("012 345"));
    }
    @Test public void incompleteOrNonNumericCodeIsRejected() {
        for (String code : new String[]{null, "", "12345", "1234567", "abcdef", "１２３４５６"}) {
            try { ConnectionCode.normalize(code); fail("Accepted invalid code"); }
            catch (IllegalArgumentException expected) {}
        }
    }
    @Test public void discoveredLaptopHasSafeNameAndAddress() {
        DiscoveredHost host = new DiscoveredHost(ID, " Laptop\nName ", "192.0.2.10", 8766);
        assertEquals("LaptopName", host.name);
        assertEquals("192.0.2.10", host.address);
        assertEquals(8766, host.port);
        assertEquals("Laptop", new DiscoveredHost(ID, "", "127.0.0.1", 1).name);
    }
    @Test public void invalidDiscoveryValuesAreRejected() {
        for (String address : new String[]{"", "localhost", "1.2.3", "1.2.3.256", "1.2.3.-1", "1.2.3.4.5"}) {
            try { new DiscoveredHost(ID, "Laptop", address, 8766); fail("Accepted invalid address"); }
            catch (IllegalArgumentException expected) {}
        }
        for (int port : new int[]{0, -1, 65536}) {
            try { new DiscoveredHost(ID, "Laptop", "192.0.2.10", port); fail("Accepted invalid port"); }
            catch (IllegalArgumentException expected) {}
        }
    }
    @Test public void malformedLaptopIdentityIsRejected() {
        try { new DiscoveredHost("bad-id", "Laptop", "192.0.2.10", 8766); fail(); }
        catch (IllegalArgumentException expected) {}
    }
}
