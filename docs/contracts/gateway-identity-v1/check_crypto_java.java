import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.KeyFactory;
import java.security.MessageDigest;
import java.security.Signature;
import java.security.spec.X509EncodedKeySpec;
import java.util.Base64;
import java.util.HexFormat;

/** JDK 17 RSA and raw-byte hash interoperability check, not JWT middleware.
 * This does not validate the JSON profile, authorization or token lifetime.
 * Run: java check_crypto_java.java crypto-cases.tsv
 */
class check_crypto_java {
    public static void main(String[] args) throws Exception {
        if (args.length != 1) throw new IllegalArgumentException("Pass crypto-cases.tsv");
        var decoder = Base64.getDecoder();
        int signatures = 0;
        int hashes = 0;
        for (String line : Files.readAllLines(Path.of(args[0]), StandardCharsets.UTF_8)) {
            String[] row = line.split("\t", -1);
            if (row[0].equals("rsa")) {
                var key = KeyFactory.getInstance("RSA").generatePublic(new X509EncodedKeySpec(decoder.decode(row[2])));
                var verifier = Signature.getInstance("SHA256withRSA");
                verifier.initVerify(key);
                verifier.update(decoder.decode(row[3]));
                boolean actual = verifier.verify(decoder.decode(row[4]));
                if (actual != Boolean.parseBoolean(row[5])) throw new AssertionError(row[1]);
                signatures++;
            } else if (row[0].equals("sha256")) {
                String actual = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(decoder.decode(row[2])));
                if (!actual.equals(row[3])) throw new AssertionError(row[1]);
                hashes++;
            } else throw new IllegalArgumentException("Unknown record: " + row[0]);
        }
        System.out.println("Java RSA checks passed: " + signatures + "; exact-byte SHA-256 checks passed: " + hashes + ".");
    }
}
