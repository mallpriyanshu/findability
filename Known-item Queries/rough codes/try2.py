from tqdm import tqdm

# lucene imports
import lucene
from org.apache.lucene.search import IndexSearcher
from org.apache.lucene.index import DirectoryReader, Term, PostingsEnum, MultiTerms
from org.apache.lucene.store import FSDirectory, SimpleFSDirectory
from org.apache.lucene.util import BytesRefIterator
from java.io import File


# start lucene virtual machine
lucene.initVM()


FIELDNAME = 'CONTENTS'       # Lucene index field name for content of the doc
corpus_name = 'WT10g'
indexPath = '../../../wt10g/index_wt10g_cleaned'   # Lucene index directory path

# Open the Lucene index directory
directory = FSDirectory.open(File(indexPath).toPath())
reader = DirectoryReader.open(directory)

terms = MultiTerms.getTerms(reader, FIELDNAME)
terms_enum = terms.iterator()
count = 0
for term in tqdm(BytesRefIterator.cast_(terms_enum), desc='P(t) computation'):
    count += 1

print(count)