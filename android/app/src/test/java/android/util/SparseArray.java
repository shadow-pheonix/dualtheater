package android.util;
import java.util.*;
/** JVM-only sorted integer map used by the actual Matroska extractor. */
public class SparseArray<E> {
    private final TreeMap<Integer,E> values=new TreeMap<>();
    public SparseArray() {}
    public SparseArray(int capacity) {}
    public E get(int key){return values.get(key);}
    public E get(int key,E fallback){return values.getOrDefault(key,fallback);}
    public void put(int key,E value){values.put(key,value);}
    public void append(int key,E value){put(key,value);}
    public int size(){return values.size();}
    public E valueAt(int index){return new ArrayList<>(values.values()).get(index);}
    public int keyAt(int index){return new ArrayList<>(values.keySet()).get(index);}
    public void clear(){values.clear();}
    public void remove(int key){values.remove(key);}
}
