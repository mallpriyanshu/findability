import org.apache.lucene.analysis.en.EnglishAnalyzer;
import org.apache.lucene.analysis.core.WhitespaceAnalyzer;
import org.apache.lucene.index.DirectoryReader;
import org.apache.lucene.index.IndexReader;
import org.apache.lucene.index.Term;
import org.apache.lucene.queryparser.classic.ParseException;
import org.apache.lucene.queryparser.classic.QueryParser;
import org.apache.lucene.search.Query;
import org.apache.lucene.search.TermQuery;
import org.apache.lucene.search.IndexSearcher;
import org.apache.lucene.search.ScoreDoc;
import org.apache.lucene.search.TopDocs;
import org.apache.lucene.search.similarities.LMDirichletSimilarity;
import org.apache.lucene.search.similarities.BM25Similarity;
import org.apache.lucene.search.similarities.DFRSimilarity;
import org.apache.lucene.search.similarities.*;
import org.apache.lucene.store.FSDirectory;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import me.tongfei.progressbar.ProgressBar;
import me.tongfei.progressbar.ProgressBarStyle;

import com.google.gson.Gson;
import com.google.gson.reflect.TypeToken;
import java.lang.reflect.Type;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.ObjectInputStream;
import java.nio.file.Paths;
import java.io.FileReader;
import java.io.FileWriter;
import java.util.*;
import java.util.List;
import java.util.stream.Collectors;
import java.util.stream.IntStream;


import java.util.concurrent.ExecutorService;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.Executors;
import java.util.concurrent.ForkJoinPool;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.ConcurrentHashMap;

import java.text.DecimalFormat;
import java.time.Duration;
import java.time.temporal.ChronoUnit;


public class FindabilityExperiment {
    private static final String FIELDNAME = "CONTENTS";
    private static final String indexPath = "../../../../../wt10g/index_wt10g_cleaned";
    private static final String queriesJSONPath = "../../../Known-item Queries/WT10g/queries_WT10g.json";
    private static final Integer c = 100;

    private static final Logger logger = LoggerFactory.getLogger(FindabilityExperiment.class);

    public static void main(String[] args) throws IOException, ParseException {
        WhitespaceAnalyzer analyzer = new WhitespaceAnalyzer();
        
        // // BM25
        // float k1 = 1.2f;
        // float b = 0.75f;
        // BM25Similarity similarityModel = new BM25Similarity(k1, b);
        // String similarityModelName = "bm25";

        // LM-Dir
        float mu = 1000.0f;
        LMDirichletSimilarity similarityModel = new LMDirichletSimilarity(mu);
        String similarityModelName = "lmdir";

        // // DFR PL2
        // BasicModel bm = new BasicModelIne();
        // AfterEffect ae = new AfterEffectL();
        // Normalization nor = new NormalizationH2();
        // DFRSimilarity similarityModel = new DFRSimilarity(bm, ae, nor);
        // String similarityModelName = "dfr-pl2";

        Map<Integer, List<Integer>> fd = new ConcurrentHashMap<>();

        try (IndexReader indexReader = DirectoryReader.open(FSDirectory.open(Paths.get(indexPath)))) {
            IndexSearcher searcher = new IndexSearcher(indexReader);
            searcher.setSimilarity(similarityModel);

            ForkJoinPool forkJoinPool = new ForkJoinPool(Runtime.getRuntime().availableProcessors());

            Map<String, List<String>> queries = loadQueriesDictFromJson(queriesJSONPath);

            try (ProgressBar pb = new ProgressBar("LM-Dir:", queries.size(), 1, System.err, ProgressBarStyle.ASCII, " docs", 1, true, new DecimalFormat("0.0"), ChronoUnit.SECONDS, 0, Duration.ZERO)) {
                List<Map<String, List<String>>> queryChunks = splitMap(queries, forkJoinPool.getParallelism());
                queries = null;

                forkJoinPool.submit(() -> {
                    queryChunks.parallelStream().forEach(chunk -> {
                        chunk.forEach((luceneDocid, queriesList) -> {
                            try {
                                retrieve(luceneDocid, queriesList, fd, analyzer, searcher);
                                pb.step(); // Update the progress bar
                            } catch (ParseException | IOException e) {
                                logger.error("Error retrieving query", e);
                            }
                        });
                    });
                }).get();
            } catch (InterruptedException | ExecutionException e) {
                logger.error("Error processing query chunks", e);
            }

            forkJoinPool.shutdown();
            try {
                forkJoinPool.awaitTermination(Long.MAX_VALUE, TimeUnit.NANOSECONDS);
            } catch (InterruptedException e) {
                logger.error("Error waiting for fork-join pool to terminate", e);
            }

            if (forkJoinPool.isTerminated()) {
                try (FileWriter writer = new FileWriter(String.format("../../WT10g/ranks/fd_ranks_%s_%.2f.json", similarityModelName, mu))) {
                    Gson gson = new Gson();
                    gson.toJson(fd, writer);
                    System.out.println("Results saved to file.");
                } catch (IOException e) {
                    logger.error("Error writing results to file", e);
                }
            }
        }

        System.out.println("\nCompleted!\n");
    }

    private static List<Map<String, List<String>>> splitMap(Map<String, List<String>> queries, int chunks) {
        List<Map<String, List<String>>> result = new ArrayList<>();

        int chunkSize = (queries.size() + chunks - 1) / chunks;
        List<String> keys = new ArrayList<>(queries.keySet());

        for (int i = 0; i < chunks; i++) {
            int startIndex = i * chunkSize;
            int endIndex = Math.min(startIndex + chunkSize, queries.size());
            List<String> subKeys = keys.subList(startIndex, endIndex);
            
            Map<String, List<String>> subMap = new HashMap<>();
            for (String key : subKeys) {
                subMap.put(key, queries.get(key));
            }

            result.add(subMap);
        }

        return result;
    }

    private static void retrieve(String luceneDocid, List<String> queriesList, Map<Integer, List<Integer>> fd, WhitespaceAnalyzer analyzer, IndexSearcher searcher) throws ParseException, IOException {
        if (luceneDocid == null || queriesList == null || analyzer == null || searcher == null || fd == null) {
            logger.error("One or more required objects are null");
            return;
        }
        int intLuceneDocid = Integer.parseInt(luceneDocid);
        List<Integer> ranks = new ArrayList<>();
        for (String query : queriesList) {
            QueryParser queryParser = new QueryParser(FIELDNAME, analyzer);
            Query luceneQuery = queryParser.parse(QueryParser.escape(query));
            TopDocs topDocs = searcher.search(luceneQuery, c); // Search for top c results
            
            // Find the rank of the luceneDocid in the search result
            int rank = -1;
            ScoreDoc[] scoreDocs = topDocs.scoreDocs;
            for (int i = 0; i < scoreDocs.length; i++) {
                int docid = scoreDocs[i].doc;
                if (intLuceneDocid == docid) {
                    rank = i + 1; // Rank starts from 1
                    break;
                }
            }
            // Append the rank
            ranks.add(rank);
        }
        fd.put(intLuceneDocid, ranks);
    }


    @SuppressWarnings("unchecked")
    private static Map<String, List<String>> loadQueriesDictFromJson(String filename) {
    Map<String, List<String>> queriesDict = new HashMap<>();
    try {
        Gson gson = new Gson();
        Type mapType = new TypeToken<Map<String, List<String>>>(){}.getType();
        FileReader fileReader = new FileReader(filename);
        queriesDict = gson.fromJson(fileReader, mapType);
        fileReader.close();
    } catch (IOException e) {
        logger.error("Error loading queries from JSON file", e);
    }
    return queriesDict;
}

}

